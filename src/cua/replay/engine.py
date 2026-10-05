"""Deterministic replay: run a compiled capability against a live page,
with no model in the decision loop. Login happens before this is called
(see docs/DECISIONS.md D3) — entry.login_script_ref is advisory metadata,
not something this engine dispatches dynamically.
"""

import os
import re
import time
import uuid
from decimal import Decimal
from typing import Any

from playwright.async_api import Page

from cua.artifact.conditions import Condition
from cua.artifact.schema import Capability, Detector, OutputField, Step
from cua.artifact.store import content_sha256
from cua.replay.checks import evaluate
from cua.replay.result import (
    BusinessOutcomeResult,
    Escalated,
    Failed,
    RunResultBase,
    StepTrace,
    Succeeded,
)
from cua.replay.templating import render
from cua.surface.resolve import resolve

POLL_MS = 150


def _apply_transforms(raw: str, transforms: list[str]) -> Any:
    value: Any = raw
    for t in transforms:
        if t == "strip":
            value = str(value).strip()
        elif t == "remove_dollar_sign":
            value = str(value).replace("$", "").strip()
        elif t == "remove_commas":
            value = str(value).replace(",", "")
        elif t == "to_decimal":
            value = Decimal(str(value))
        elif t == "to_int":
            value = int(str(value))
        else:
            raise ValueError(f"unknown transform: {t}")
    return value


def _validate_inputs(capability: Capability, inputs: dict[str, Any]) -> str | None:
    for param in capability.inputs:
        if param.name not in inputs:
            return f"missing required input: {param.name}"
        if param.pattern and not re.match(param.pattern, str(inputs[param.name])):
            return f"input {param.name!r} does not match pattern {param.pattern!r}"
    return None


async def _wait_for(
    page: Page,
    condition: Condition,
    *,
    labels: dict[str, str],
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    timeout_ms: int,
) -> bool:
    elapsed = 0
    while True:
        if await evaluate(page, condition, labels=labels, inputs=inputs, outputs=outputs):
            return True
        if elapsed >= timeout_ms:
            return False
        await page.wait_for_timeout(POLL_MS)
        elapsed += POLL_MS


async def _armed_detector(
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


async def _race_post_and_detectors(
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
        hit = await _armed_detector(
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


def _result_for_detector(detector: Detector, base: dict, step_id: str) -> RunResultBase:
    if detector.kind == "business_outcome":
        return BusinessOutcomeResult(**base, outcome=detector.outcome or detector.id)
    if detector.kind == "escalate":
        return Escalated(**base, reason=f"detector {detector.id} fired", step_id=step_id)
    # hard_failure, and recoverable (handler execution is a later story —
    # see docs/DECISIONS.md — surfaced honestly as a hard failure for now).
    return Failed(
        **base,
        code="app_error",
        step_id=step_id,
        expected="no hard_failure/unhandled-recoverable detector",
        observed=f"detector {detector.id!r} ({detector.kind}) fired",
    )


async def _act(
    handle, page: Page, step: Step, inputs: dict[str, Any], labels: dict[str, str]
) -> None:
    value = render(step.value or "", inputs, labels)
    if step.action == "click":
        await handle.click()
    elif step.action == "type":
        await handle.fill(value)
    elif step.action == "type_secret":
        secret = os.environ.get(f"CUA_SECRET_{(step.value or '').upper()}", "")
        await handle.fill(secret)
    elif step.action == "select":
        await handle.select_option(value)
    elif step.action == "press":
        await handle.press(value)
    elif step.action == "extract":
        pass  # extraction runs after all steps complete, from OutputField.extract
    else:
        raise ValueError(f"action {step.action!r} requires a target but isn't handled")


async def _extract_outputs(
    page: Page, capability: Capability, *, labels: dict[str, str]
) -> tuple[dict[str, Any], OutputField | None]:
    outputs: dict[str, Any] = {}
    for field in capability.outputs:
        res = await resolve(page, field.extract.target, labels)
        if res.handle is None:
            if field.required:
                return outputs, field
            continue
        if field.extract.read == "text":
            raw = await res.handle.evaluate("el => el.innerText || el.textContent || ''")
        elif field.extract.read == "value":
            raw = await res.handle.evaluate("el => el.value || ''")
        else:
            raw = await res.handle.evaluate(
                f"el => el.getAttribute('{field.extract.attr_name}') || ''"
            )
        outputs[field.name] = _apply_transforms(raw, field.extract.transforms)
    return outputs, None


async def replay(
    page: Page,
    capability: Capability,
    inputs: dict[str, Any],
    *,
    base_url: str = "",
    entry_timeout_ms: int = 10000,
) -> RunResultBase:
    run_id = str(uuid.uuid4())
    labels = capability.labels
    outputs: dict[str, Any] = {}
    trace: list[StepTrace] = []

    def base(**extra: Any) -> dict:
        return {
            "run_id": run_id,
            "capability": capability.id,
            "version": capability.version,
            "effective_sha256": content_sha256(capability),
            "trace": trace,
            **extra,
        }

    error = _validate_inputs(capability, inputs)
    if error:
        return Failed(
            **base(
                code="input_invalid", step_id="<inputs>", expected="valid inputs", observed=error
            )
        )

    await page.goto(base_url.rstrip("/") + capability.entry.route)
    entry_ready = await _wait_for(
        page,
        capability.entry.condition,
        labels=labels,
        inputs=inputs,
        outputs=outputs,
        timeout_ms=entry_timeout_ms,
    )
    if not entry_ready:
        return Failed(
            **base(
                code="target_unresolved",
                step_id="<entry>",
                expected="entry ready",
                observed="timed out",
            )
        )

    for step in capability.steps:
        start = time.monotonic()

        hit = await _armed_detector(
            page, capability, step.id, labels=labels, inputs=inputs, outputs=outputs
        )
        if hit:
            return _result_for_detector(hit, base(), step.id)

        if step.pre is not None:
            pre_ok = await evaluate(page, step.pre, labels=labels, inputs=inputs, outputs=outputs)
            if not pre_ok:
                return Failed(
                    **base(
                        code="target_unresolved",
                        step_id=step.id,
                        expected="pre-condition true",
                        observed="pre-condition false",
                    )
                )

        strategy_used = None
        if step.target is not None:
            res = await resolve(page, step.target, labels)
            if res.handle is None:
                return Failed(
                    **base(
                        code="target_unresolved",
                        step_id=step.id,
                        expected=f"one of strategies {[s.by for s in step.target.strategies]}",
                        observed=f"attempts: {res.attempts}",
                    )
                )
            strategy_used = res.strategy_used
            await _act(res.handle, page, step, inputs, labels)
        elif step.action == "navigate":
            await page.goto(render(step.value or "", inputs, labels))
        elif step.action == "press":
            await page.keyboard.press(render(step.value or "", inputs, labels))
        else:
            raise ValueError(f"step {step.id!r} ({step.action}) needs a target")

        trace.append(
            StepTrace(
                step_id=step.id,
                strategy_used=strategy_used,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        )

        satisfied, hit = await _race_post_and_detectors(
            page,
            step,
            capability,
            labels=labels,
            inputs=inputs,
            outputs=outputs,
        )
        if hit:
            return _result_for_detector(hit, base(), step.id)
        if not satisfied:
            return Failed(
                **base(
                    code="postcondition_timeout",
                    step_id=step.id,
                    expected=str(step.post.when),
                    observed="post-condition not satisfied in time",
                )
            )

    outputs, failing_field = await _extract_outputs(page, capability, labels=labels)
    if failing_field is not None:
        return Failed(
            **base(
                code="target_unresolved",
                step_id="<outputs>",
                expected=f"output {failing_field.name!r} target resolvable",
                observed="extraction target did not resolve",
            )
        )

    checkpoint_ok = await evaluate(
        page, capability.checkpoint.when, labels=labels, inputs=inputs, outputs=outputs
    )
    if not checkpoint_ok:
        return Failed(
            **base(
                code="checkpoint_mismatch",
                step_id="<checkpoint>",
                expected=str(capability.checkpoint.when),
                observed="checkpoint condition false",
            )
        )

    return Succeeded(**base(outputs=outputs))
