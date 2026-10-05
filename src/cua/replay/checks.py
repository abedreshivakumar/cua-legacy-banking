"""Evaluate a Condition against the live page."""

import re
from typing import Any

from playwright.async_api import Page

from cua.artifact.conditions import Condition
from cua.replay.templating import render
from cua.surface.resolve import frame_for_scope, resolve


async def evaluate(
    page: Page,
    condition: Condition,
    *,
    labels: dict[str, str],
    inputs: dict[str, Any],
    outputs: dict[str, Any],
) -> bool:
    if condition.type == "text_present":
        frame = frame_for_scope(page, condition.scope) or page.main_frame
        body = frame.locator("body")
        text = await (body.inner_text() if condition.visible_only else body.text_content())
        text = text or ""
        if condition.pattern:
            return re.search(render(condition.pattern, inputs, labels), text) is not None
        return render(condition.text or "", inputs, labels) in text

    if condition.type == "element_resolvable":
        res = await resolve(page, condition.target, labels)
        return res.handle is not None

    if condition.type == "location_matches":
        return re.search(condition.route_pattern, page.url) is not None

    if condition.type == "outputs_present":
        return all(name in outputs for name in condition.names)

    if condition.type == "all":
        for c in condition.conditions:
            if not await evaluate(page, c, labels=labels, inputs=inputs, outputs=outputs):
                return False
        return True

    if condition.type == "any":
        for c in condition.conditions:
            if await evaluate(page, c, labels=labels, inputs=inputs, outputs=outputs):
                return True
        return False

    if condition.type == "not":
        return not await evaluate(
            page, condition.condition, labels=labels, inputs=inputs, outputs=outputs
        )

    raise ValueError(f"unknown condition type: {condition.type}")
