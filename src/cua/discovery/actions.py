"""Execute one computer-toolset member action against the live page.

Click actions resolve-then-act (D2): hit-test the raw coordinate, build a
TargetDescriptor from the facts, resolve it, and act on the resolved
handle — never the raw coordinate. What ends up recorded is provably what
was actually clicked, by construction, not by a post-hoc comparison.
"""

import base64
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from cua.artifact.targets import ScopeStep, TargetDescriptor
from cua.discovery.targeting import target_from_facts
from cua.surface.hittest import hit_test
from cua.surface.resolve import frame_for_scope, resolve

_NAVIGATION_GRACE_MS = 1500


async def _click_and_settle(page: Page, clicker: Any, frame_path: list[str] | None) -> None:
    """Run `clicker()` while listening for a navigation on the clicked
    frame, so a caller inspecting page state right after can't race a
    navigation that was triggered but hadn't registered yet.

    `expect_navigation()` has to wrap the click (listener attached first) —
    calling `wait_for_load_state()` *after* the click isn't enough: if the
    navigation hasn't been registered by Playwright's internal tracking at
    that instant, it sees the frame's still-current pre-click load state and
    returns immediately. Most clicks don't navigate at all, so a timeout
    here is the expected, non-error outcome, not a failure.
    """
    scope = [ScopeStep(name=n) for n in (frame_path or []) if n]
    frame = frame_for_scope(page, scope) or page.main_frame
    try:
        async with frame.expect_navigation(timeout=_NAVIGATION_GRACE_MS):
            await clicker()
    except PlaywrightTimeoutError:
        pass


async def execute_action(
    page: Page, name: str, raw_input: dict[str, Any]
) -> tuple[str | None, dict[str, Any] | None, TargetDescriptor | None]:
    """Run one member action.

    Returns (screenshot_b64_if_any, resolved_facts_if_any, target_if_resolved).
    `target` is the TargetDescriptor the action was actually dispatched
    through — None means the hit facts couldn't be turned into a uniquely
    resolvable target, so this step fell back to the raw coordinate and
    should be flagged by the recorder (S8), not silently kept.
    """
    if name == "screenshot":
        png = await page.screenshot()
        return base64.b64encode(png).decode(), None, None

    if name in ("left_click", "double_click", "right_click", "triple_click"):
        coord = raw_input.get("coordinate", [0, 0])
        x, y = coord[0], coord[1]
        facts = await hit_test(page, x, y)
        if facts is None:
            await page.mouse.click(x, y)
            return None, None, None

        target = target_from_facts(facts)
        if target is not None:
            res = await resolve(page, target, {})
            if res.handle is not None:
                await _click_and_settle(page, res.handle.click, facts.get("framePath"))
                return None, facts, target

        # couldn't build or uniquely resolve a target from the hit facts —
        # fall back to the raw coordinate, but report target=None so the
        # recorder flags this step rather than keeping it silently.
        await _click_and_settle(page, lambda: page.mouse.click(x, y), facts.get("framePath"))
        return None, facts, None

    if name == "type":
        await page.keyboard.type(raw_input.get("text", ""))
        return None, None, None

    if name == "key":
        await page.keyboard.press(raw_input.get("text", ""))
        return None, None, None

    if name == "wait":
        await page.wait_for_timeout(500)
        return None, None, None

    # Unsupported in v0 (e.g. scroll, zoom, drag) — surfaced honestly rather
    # than silently doing nothing, so a discovery run that needs it fails
    # loudly instead of looking like it succeeded.
    return None, {"unsupported_action": name}, None
