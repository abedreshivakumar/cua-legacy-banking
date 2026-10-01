"""Resolve a top-level (x, y) coordinate to the real element under it,
recursing through nested frames with offset correction.
"""

from playwright.async_api import Page

_HIT_TEST_JS = """
([xIn, yIn]) => {
  let doc = document;
  let localX = xIn, localY = yIn;
  const framePath = [];
  for (let depth = 0; depth < 10; depth++) {
    const el = doc.elementFromPoint(localX, localY);
    if (!el) return null;
    if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
      const rect = el.getBoundingClientRect();
      localX = localX - rect.left;
      localY = localY - rect.top;
      framePath.push(el.getAttribute('name') || el.getAttribute('src') || '');
      doc = el.contentDocument;
      if (!doc) return null;
      continue;
    }
    return {
      tag: el.tagName,
      text: (el.innerText || el.value || '').slice(0, 80).trim(),
      name: el.getAttribute('name'),
      type: el.getAttribute('type'),
      href: el.getAttribute('href'),
      framePath,
    };
  }
  return null;
}
"""


async def hit_test(page: Page, x: float, y: float) -> dict | None:
    """Find the element at (x, y) in top-level viewport coordinates,
    descending through same-origin <frame>/<iframe> boundaries."""
    return await page.evaluate(_HIT_TEST_JS, [x, y])
