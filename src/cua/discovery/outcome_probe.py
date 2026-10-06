"""Turning a probe discovery run into a synthesized business-outcome
detector (S11). The happy-path discovery run that compile_capability
works from never sees a business-outcome page, so the compiler emits no
detectors at all — detector synthesis is deliberately a separate,
probe-run exercise: run discovery again against an input expected to
diverge, see what actually changed on screen, and build a detector from
that diff rather than guessing at a pattern.

The negative control is a runtime check, not a text comparison: it
re-evaluates the synthesized Condition against a *live* happy-path page,
using the exact same visible-only reading replay's TextPresent uses, so
a detector that would also fire on the happy path is rejected here, not
discovered later in production.
"""

from playwright.async_api import Page

from cua.artifact.conditions import TextPresent
from cua.artifact.schema import Detector
from cua.discovery.loop import DiscoveryResult
from cua.replay.checks import evaluate


class ProbeError(Exception):
    """A probe run can't be turned into a detector — see the message."""


def _reported_outcome(result: DiscoveryResult) -> dict | None:
    for e in result.action_log:
        if e.kind == "custom_tool" and e.name == "report_outcome":
            return e.input
    return None


def _probed_literals(result: DiscoveryResult) -> list[str]:
    """Every literal value typed during the probe run — excluded from
    candidate signal lines, same deny-by-default spirit as the compiler's
    literal handling (D6): a detector built from one probe input must not
    silently only ever match THAT input's own value."""
    return [
        e.input["text"]
        for e in result.action_log
        if e.kind == "member_action" and e.name == "type" and e.input.get("text")
    ]


def synthesize_outcome_detector(
    probe_result: DiscoveryResult, *, probe_page_text: str, happy_page_text: str
) -> Detector:
    """Builds a business_outcome Detector from a completed probe run.

    `probe_page_text` / `happy_page_text` must each be captured with
    `replay.checks.visible_page_text()` — the same visible-only reading
    the resulting detector's TextPresent will use at replay time, so
    what's synthesized here is checked against exactly what replay sees.
    """
    if probe_result.status != "completed":
        raise ProbeError(f"probe run did not complete (status={probe_result.status!r})")
    reported = _reported_outcome(probe_result)
    if reported is None or reported.get("kind") != "business_outcome":
        raise ProbeError("probe run never reported a business_outcome")

    probe_lines = {ln.strip() for ln in probe_page_text.splitlines() if ln.strip()}
    happy_lines = {ln.strip() for ln in happy_page_text.splitlines() if ln.strip()}
    literals = _probed_literals(probe_result)
    unique = [
        ln
        for ln in sorted(probe_lines - happy_lines, key=len, reverse=True)
        if not any(lit in ln for lit in literals)
    ]
    if not unique:
        raise ProbeError(
            "no visible text is unique to the probe outcome page (once lines containing "
            "this run's own typed literals are excluded) — refusing to build a detector "
            "that can't be told apart from the happy path, or that only matches this input"
        )

    return Detector(
        id=reported["name"],
        kind="business_outcome",
        outcome=reported["name"],
        when=TextPresent(text=unique[0]),
        active="always",
        priority=10,
        origin="discovered",
    )


async def passes_negative_control(page: Page, detector: Detector) -> bool:
    """True if the detector's condition does NOT fire on `page`'s current
    state. Call this against a live happy-path page before trusting a
    synthesized detector — never skip it in favor of comparing strings."""
    fired = await evaluate(page, detector.when, labels={}, inputs={}, outputs={})
    return not fired
