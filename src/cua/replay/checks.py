"""Evaluate a Condition against the live page."""

import re
from typing import Any

from playwright.async_api import Page

from cua.artifact.conditions import Condition
from cua.artifact.targets import ScopeStep
from cua.replay.templating import render
from cua.surface.resolve import frame_for_scope, resolve

# A frameset's top-level document has no <body> at all; a locator action
# against one waits out Playwright's default ~30s actionability timeout
# before failing. Fail fast instead — found twice (see docs/DECISIONS.md
# D18, and again here), which is why this constant exists at all.
_TEXT_TIMEOUT_MS = 500


async def _page_text(page: Page, scope: list[ScopeStep], *, visible_only: bool) -> str:
    """Text for a scoped frame, or — scope empty — every live frame
    concatenated, since an unscoped condition means "anywhere on the
    page", not just whichever frame happens to be main_frame."""
    frames = [frame_for_scope(page, scope)] if scope else list(page.frames)
    chunks: list[str] = []
    for frame in frames:
        if frame is None or frame.is_detached():
            continue
        try:
            body = frame.locator("body")
            text = await (
                body.inner_text(timeout=_TEXT_TIMEOUT_MS)
                if visible_only
                else body.text_content(timeout=_TEXT_TIMEOUT_MS)
            )
        except Exception:  # noqa: BLE001 — no body / mid-navigation isn't fatal here
            continue
        if text:
            chunks.append(text)
    return "\n".join(chunks)


async def visible_page_text(page: Page) -> str:
    """Every live frame's visible text concatenated — the same reading an
    unscoped TextPresent condition uses. Exposed for detector synthesis
    (discovery/outcome_probe.py), which diffs two pages' visible text
    outside the Condition language, so it has to read it the identical
    way replay will."""
    return await _page_text(page, [], visible_only=True)


async def evaluate(
    page: Page,
    condition: Condition,
    *,
    labels: dict[str, str],
    inputs: dict[str, Any],
    outputs: dict[str, Any],
) -> bool:
    if condition.type == "text_present":
        text = await _page_text(page, condition.scope, visible_only=condition.visible_only)
        if condition.pattern:
            return re.search(render(condition.pattern, inputs, labels), text) is not None
        return render(condition.text or "", inputs, labels) in text

    if condition.type == "element_resolvable":
        res = await resolve(page, condition.target, labels)
        return res.handle is not None

    if condition.type == "location_matches":
        # Checked against every live frame, not just the top-level page —
        # a redirect to /login typically lands on whichever FRAME made the
        # request that triggered it (e.g. the "work" frame's own POST),
        # not a top-level navigation. page.url alone would never match.
        pattern = re.compile(condition.route_pattern)
        return any(pattern.search(f.url) for f in page.frames if not f.is_detached())

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
