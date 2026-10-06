"""Per-step primitives for replay: waiting on a condition, running one
step's action, and the output-value transform chain. Split out of
engine.py to keep that file under the size guideline.
"""

import os
from decimal import Decimal
from typing import Any

from playwright.async_api import Page

from cua.artifact.conditions import Condition
from cua.artifact.schema import Step
from cua.replay.checks import evaluate
from cua.replay.templating import render
from cua.surface.resolve import frame_for_scope, resolve

POLL_MS = 150


def apply_transforms(raw: str, transforms: list[str]) -> Any:
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


async def wait_for(
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


async def run_action(
    page: Page, step: Step, inputs: dict[str, Any], labels: dict[str, str]
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve the step's target (if any) and act on it.

    Returns (strategy_used, None) on success, or (None, error_fields) where
    error_fields is a dict of Failed(...) kwargs (minus step_id, which the
    caller adds) for the caller to turn into a terminal result.
    """
    if step.target is not None:
        res = await resolve(page, step.target, labels)
        if res.handle is None:
            strategies = [s.by for s in step.target.strategies]
            return None, {
                "code": "target_unresolved",
                "expected": f"one of strategies {strategies}",
                "observed": f"attempts: {res.attempts}",
            }
        await _act(res.handle, page, step, inputs, labels)
        settle_frame = frame_for_scope(page, step.target.scope) or page.main_frame
        await settle_frame.wait_for_load_state("domcontentloaded")
        return res.strategy_used, None

    if step.action == "navigate":
        await page.goto(render(step.value or "", inputs, labels))
        return None, None
    if step.action == "press":
        await page.keyboard.press(render(step.value or "", inputs, labels))
        return None, None

    raise ValueError(f"step {step.id!r} ({step.action}) needs a target")
