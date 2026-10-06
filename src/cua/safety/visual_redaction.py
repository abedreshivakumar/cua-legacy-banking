"""Masking a known PII-bearing screen region before a screenshot is
taken. Text redaction (redaction.py) can't touch an image — a screenshot
of a results page shows a member's SSN/DOB as pixels, not greppable
text — so this is the other half of the same concern.

The mask has to be injected into the *target frame's own* document, not
the top-level page: this app's frameset top document has no real
`<body>` (a recurring fact in this codebase — see docs/DECISIONS.md
D18/D20) — `document.body` on a frameset resolves to the `<frameset>`
element itself, which doesn't composite ordinary block children, so an
overlay appended there is a silent no-op (confirmed directly: no
exception, but nothing painted). Appending into the frame's own body
works, which means the box has to be in that frame's LOCAL coordinates,
not the page-absolute ones `element_handle.bounding_box()` returns —
converted here by subtracting the frame's own absolute offset.
"""

from playwright.async_api import Page

_MASK_ID = "__cua_redaction_mask__"


async def mask_frame_region(page: Page, frame_name: str, box: dict[str, float]) -> bytes:
    """Screenshots `page` with `box` (page-absolute x/y/width/height, as
    returned by `element_handle.bounding_box()`) blacked out, wherever it
    falls within the frame named `frame_name`."""
    frame = page.frame(name=frame_name)
    if frame is None:
        raise ValueError(f"no frame named {frame_name!r}")
    frame_element = await frame.frame_element()
    frame_box = await frame_element.bounding_box()
    if frame_box is None:
        raise ValueError(f"frame {frame_name!r} has no bounding box — is it visible?")

    local_box = {
        "x": box["x"] - frame_box["x"],
        "y": box["y"] - frame_box["y"],
        "width": box["width"],
        "height": box["height"],
    }
    await frame.evaluate(
        """([maskId, b]) => {
            const d = document.createElement('div');
            d.id = maskId;
            d.style.position = 'fixed';
            d.style.left = b.x + 'px';
            d.style.top = b.y + 'px';
            d.style.width = b.width + 'px';
            d.style.height = b.height + 'px';
            d.style.background = 'black';
            d.style.zIndex = '2147483647';
            document.body.appendChild(d);
        }""",
        [_MASK_ID, local_box],
    )
    try:
        return await page.screenshot()
    finally:
        await frame.evaluate("(maskId) => document.getElementById(maskId)?.remove()", _MASK_ID)
