"""Deterministic replay: run a compiled capability against a live page,
with no model in the decision loop. Login happens before this is called
(see docs/DECISIONS.md D3) — entry.login_script_ref is advisory metadata.
A caller-supplied `login_fn` is the one exception: a recoverable
`relogin` handler needs to actually re-authenticate mid-run, and reuses
whatever the caller used for the initial login, never a dynamic lookup
of the script_ref string. Detector matching and handler execution live
in recovery.py — this file is the per-step act/wait/advance loop.
"""

import re
import time
import uuid
from typing import Any, Literal

from playwright.async_api import Page

from cua.artifact.schema import Capability, OutputField, Step
from cua.artifact.store import content_sha256
from cua.replay.checks import evaluate
from cua.replay.recovery import (
    LoginFn,
    RecoveryState,
    armed_detector,
    race_post_and_detectors,
    run_handler,
)
from cua.replay.result import Failed, RunResult, StepTrace, Succeeded
from cua.replay.steps import apply_transforms, run_action, wait_for
from cua.surface.resolve import resolve

MAX_RESTARTS = 2


def _validate_inputs(capability: Capability, inputs: dict[str, Any]) -> str | None:
    for param in capability.inputs:
        if param.name not in inputs:
            return f"missing required input: {param.name}"
        if param.pattern and not re.match(param.pattern, str(inputs[param.name])):
            return f"input {param.name!r} does not match pattern {param.pattern!r}"
    return None


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
        outputs[field.name] = apply_transforms(raw, field.extract.transforms)
    return outputs, None


async def replay(
    page: Page,
    capability: Capability,
    inputs: dict[str, Any],
    *,
    base_url: str = "",
    entry_timeout_ms: int = 10000,
    login_fn: LoginFn | None = None,
) -> RunResult:
    run_id = str(uuid.uuid4())
    labels = capability.labels
    outputs: dict[str, Any] = {}
    trace: list[StepTrace] = []
    state = RecoveryState()
    restarts_used = 0
    has_commit_irreversible = any(s.risk == "commit_irreversible" for s in capability.steps)

    def base(**extra: Any) -> dict:
        return {
            "run_id": run_id,
            "capability": capability.id,
            "version": capability.version,
            "effective_sha256": content_sha256(capability),
            "trace": trace,
            "recoveries": state.recoveries,
            **extra,
        }

    async def goto_entry() -> RunResult | None:
        await page.goto(base_url.rstrip("/") + capability.entry.route)
        ready = await wait_for(
            page,
            capability.entry.condition,
            labels=labels,
            inputs=inputs,
            outputs=outputs,
            timeout_ms=entry_timeout_ms,
        )
        if not ready:
            return Failed(
                **base(
                    code="target_unresolved",
                    step_id="<entry>",
                    expected="entry ready",
                    observed="timed out",
                )
            )
        return None

    async def run_step(step: Step) -> tuple[Literal["advance", "restart"], RunResult | None]:
        should_act = True
        while True:
            if should_act:
                hit = await armed_detector(
                    page, capability, step.id, labels=labels, inputs=inputs, outputs=outputs
                )
                if hit:
                    action, result = await run_handler(
                        page,
                        hit,
                        step,
                        labels=labels,
                        login_fn=login_fn,
                        has_commit_irreversible=has_commit_irreversible,
                        state=state,
                        base=base,
                    )
                    if result is not None:
                        return "advance", result
                    if action == "restart_entry":
                        return "restart", None
                    continue  # resume_step / retry_step before acting: re-check and proceed

                if step.pre is not None:
                    pre_ok = await evaluate(
                        page, step.pre, labels=labels, inputs=inputs, outputs=outputs
                    )
                    if not pre_ok:
                        return "advance", Failed(
                            **base(
                                code="target_unresolved",
                                step_id=step.id,
                                expected="pre-condition true",
                                observed="pre-condition false",
                            )
                        )

                start = time.monotonic()
                strategy_used, act_error = await run_action(page, step, inputs, labels)
                if act_error is not None:
                    return "advance", Failed(**base(**act_error, step_id=step.id))

                trace.append(
                    StepTrace(
                        step_id=step.id,
                        strategy_used=strategy_used,
                        duration_ms=int((time.monotonic() - start) * 1000),
                    )
                )
                should_act = False

            satisfied, hit = await race_post_and_detectors(
                page, step, capability, labels=labels, inputs=inputs, outputs=outputs
            )
            if satisfied:
                return "advance", None
            if hit is None:
                return "advance", Failed(
                    **base(
                        code="postcondition_timeout",
                        step_id=step.id,
                        expected=str(step.post.when),
                        observed="post-condition not satisfied in time",
                    )
                )

            action, result = await run_handler(
                page,
                hit,
                step,
                labels=labels,
                login_fn=login_fn,
                has_commit_irreversible=has_commit_irreversible,
                state=state,
                base=base,
            )
            if result is not None:
                return "advance", result
            if action == "restart_entry":
                return "restart", None
            should_act = action == "retry_step"

    error = _validate_inputs(capability, inputs)
    if error:
        return Failed(
            **base(
                code="input_invalid", step_id="<inputs>", expected="valid inputs", observed=error
            )
        )

    entry_error = await goto_entry()
    if entry_error:
        return entry_error

    step_index = 0
    while step_index < len(capability.steps):
        status, result = await run_step(capability.steps[step_index])
        if result is not None:
            return result
        if status == "restart":
            restarts_used += 1
            if restarts_used > MAX_RESTARTS:
                return Failed(
                    **base(
                        code="recovery_exhausted",
                        step_id=capability.steps[step_index].id,
                        expected=f"<= {MAX_RESTARTS} restarts",
                        observed=f"restart {restarts_used}",
                    )
                )
            entry_error = await goto_entry()
            if entry_error:
                return entry_error
            step_index = 0
            continue
        step_index += 1

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
