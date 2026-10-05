"""Execute one computer-toolset member action against the live page.

Discovery acts on raw coordinates (D0) — the hit-test result returned here
is what the recorder (S8) turns into a checked TargetDescriptor; the
coordinate itself never reaches the artifact.
"""

import base64
from typing import Any

from playwright.async_api import Page

from cua.surface.hittest import hit_test


async def execute_action(
    page: Page, name: str, raw_input: dict[str, Any]
) -> tuple[str | None, dict[str, Any] | None]:
    """Run one member action. Returns (screenshot_b64_if_any, resolved_facts_if_any)."""
    if name == "screenshot":
        png = await page.screenshot()
        return base64.b64encode(png).decode(), None

    if name in ("left_click", "double_click", "right_click", "triple_click"):
        coord = raw_input.get("coordinate", [0, 0])
        x, y = coord[0], coord[1]
        facts = await hit_test(page, x, y)
        await page.mouse.click(x, y)
        return None, facts

    if name == "type":
        await page.keyboard.type(raw_input.get("text", ""))
        return None, None

    if name == "key":
        await page.keyboard.press(raw_input.get("text", ""))
        return None, None

    if name == "wait":
        await page.wait_for_timeout(500)
        return None, None

    # Unsupported in v0 (e.g. scroll, zoom, drag) — surfaced honestly rather
    # than silently doing nothing, so a discovery run that needs it fails
    # loudly instead of looking like it succeeded.
    return None, {"unsupported_action": name}
