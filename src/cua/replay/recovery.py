"""Detector matching and recovery-handler execution for replay.

Split out of engine.py to keep it under the file-size guideline — this is
the piece that grew once S10 added real handler execution (dismiss /
relogin / backoff), not just detection.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from playwright.async_api import Page

from cua.artifact.schema import Capability, Detector, Step
from cua.replay.checks import evaluate
from cua.replay.result import BusinessOutcomeResult, Escalated, Failed, RunResult
from cua.surface.resolve import resolve

POLL_MS = 150
MAX_RUN_RECOVERIES = 5

LoginFn = Callable[[Page], Awaitable[None]]
HandlerAction = Literal["resume_step", "retry_step", "restart_entry"]


@dataclass
class RecoveryState:
    recoveries_used: int = 0
    detector_attempts: dict[str, int] = field(default_factory=dict)
    recoveries: list[str] = field(default_factory=list)


async def armed_detector(
    page: Page,
    capability: Capability,
    step_id: str,
    *,
    labels: dict[str, str],
    inputs: dict[str, Any],
    outputs: dict[str, Any],
) -> Detector | None:
    armed = [d for d in capability.detectors if d.active == "always" or step_id in d.active]
    for d in sorted(armed, key=lambda d: -d.priority):
        if await evaluate(page, d.when, labels=labels, inputs=inputs, outputs=outputs):
            return d
    return None


async def race_post_and_detectors(
    page: Page,
    step: Step,
    capability: Capability,
    *,
    labels: dict[str, str],
    inputs: dict[str, Any],
    outputs: dict[str, Any],
) -> tuple[bool, Detector | None]:
    """Poll the step's post-condition and its armed detectors together.

    A detector is checked first on every tick: if a business-outcome page
    and the post-condition's own fallback branch both happen to go true at
    once (e.g. post = Any[success-text, not-found-text]), the detector wins
    — the step is reported as that outcome, never as a bare "succeeded".
    """
    elapsed = 0
    while True:
        hit = await armed_detector(
            page, capability, step.id, labels=labels, inputs=inputs, outputs=outputs
        )
        if hit:
            return False, hit
        if await evaluate(page, step.post.when, labels=labels, inputs=inputs, outputs=outputs):
            return True, None
        if elapsed >= step.post.timeout_ms:
            return False, None
        await page.wait_for_timeout(POLL_MS)
        elapsed += POLL_MS


def result_for_non_recoverable(detector: Detector, base: dict, step_id: str) -> RunResult:
    if detector.kind == "business_outcome":
        return BusinessOutcomeResult(**base, outcome=detector.outcome or detector.id)
    if detector.kind == "escalate":
        return Escalated(**base, reason=f"detector {detector.id} fired", step_id=step_id)
    return Failed(
        **base,
        code="app_error",
        step_id=step_id,
        expected="no hard_failure detector",
        observed=f"detector {detector.id!r} fired",
    )


async def run_handler(
    page: Page,
    detector: Detector,
    step: Step,
    *,
    labels: dict[str, str],
    login_fn: LoginFn | None,
    has_commit_irreversible: bool,
    state: RecoveryState,
    base: Callable[..., dict],
) -> tuple[HandlerAction | None, RunResult | None]:
    """Returns (action, None) to continue the step loop, or (None, a
    terminal RunResult) to stop the whole replay."""
    if detector.kind != "recoverable":
        return None, result_for_non_recoverable(detector, base(), step.id)

    attempts = state.detector_attempts.get(detector.id, 0)
    if attempts >= detector.max_attempts:
        return None, Failed(
            **base(
                code="recovery_exhausted",
                step_id=step.id,
                expected=f"<= {detector.max_attempts} attempts for detector {detector.id!r}",
                observed=f"attempt {attempts + 1}",
            )
        )
    state.recoveries_used += 1
    if state.recoveries_used > MAX_RUN_RECOVERIES:
        return None, Failed(
            **base(
                code="recovery_exhausted",
                step_id=step.id,
                expected=f"<= {MAX_RUN_RECOVERIES} recoveries for the whole run",
                observed=f"recovery {state.recoveries_used}",
            )
        )
    state.detector_attempts[detector.id] = attempts + 1

    handler = detector.handler
    if handler is None:
        return None, Failed(
            **base(
                code="app_error",
                step_id=step.id,
                expected="a handler on a recoverable detector",
                observed=f"detector {detector.id!r} has none",
            )
        )

    # commit_irreversible is never retried — resume_step is the only
    # handler.then a commit step can take, and restart_entry is refused
    # outright on any capability that has one, since restarting always
    # replays every step from the beginning.
    if handler.then == "retry_step" and step.risk == "commit_irreversible":
        return None, Failed(
            **base(
                code="recovery_exhausted",
                step_id=step.id,
                expected="no retry_step on a commit_irreversible step",
                observed=f"detector {detector.id!r} requested retry_step",
            )
        )
    if handler.then == "restart_entry" and has_commit_irreversible:
        return None, Failed(
            **base(
                code="recovery_exhausted",
                step_id=step.id,
                expected="no restart_entry on a capability with a commit_irreversible step",
                observed=f"detector {detector.id!r} requested restart_entry",
            )
        )

    if handler.type == "dismiss":
        res = await resolve(page, handler.target, labels)
        if res.handle is None:
            return None, Failed(
                **base(
                    code="app_error",
                    step_id=step.id,
                    expected="dismiss handler's target resolvable",
                    observed=f"detector {detector.id!r}'s dismiss target did not resolve",
                )
            )
        await res.handle.click()
    elif handler.type == "relogin":
        if login_fn is None:
            return None, Failed(
                **base(
                    code="app_error",
                    step_id=step.id,
                    expected="a login_fn for relogin recovery",
                    observed=f"detector {detector.id!r} needs relogin but none was provided",
                )
            )
        await login_fn(page)
    elif handler.type == "backoff":
        await page.wait_for_timeout(handler.wait_ms)

    state.recoveries.append(detector.id)
    return handler.then, None
