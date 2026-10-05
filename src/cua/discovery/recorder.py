"""Verify a model's claimed output value actually appears on the live
page before trusting it — a record_output mismatch is a discovery-time
failure, not something the compiler silently inherits."""

from playwright.async_api import Page


async def verify_output_on_page(page: Page, value: str) -> bool:
    """True if `value` appears in any live frame's visible text."""
    needle = value.strip()
    if not needle:
        return False
    for frame in page.frames:
        if frame.is_detached():
            continue
        try:
            # A frameset's top-level document has no <body> at all; fail
            # fast rather than waiting out Playwright's default ~30s
            # actionability timeout per frame that doesn't have one.
            text = await frame.locator("body").inner_text(timeout=500)
        except Exception:  # noqa: BLE001 — no body / mid-navigation isn't a hard failure here
            continue
        if needle in text:
            return True
    return False
