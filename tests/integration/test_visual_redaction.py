"""S13 acceptance: masking a known PII-bearing region inside a frame
before a screenshot is taken, verified against actual decoded pixels —
not just that a `<div>` was inserted."""

import io
import os
import threading
import time
import urllib.request

import pytest
from PIL import Image
from playwright.async_api import async_playwright

from cua.safety.visual_redaction import mask_frame_region

HOST = "127.0.0.1"
PORT = 8820
BASE_URL = f"http://{HOST}:{PORT}"


@pytest.fixture(scope="module")
def live_server():
    import uvicorn

    from target_app.app import app

    os.environ["COREBANK_USER"] = "teller1"
    os.environ["COREBANK_PASSWORD"] = "testpass123"
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{BASE_URL}/__health", timeout=0.2)
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("target app did not start in time")
    yield BASE_URL
    server.should_exit = True
    thread.join(timeout=5)


async def test_masked_region_is_black_and_the_rest_of_the_frame_is_not(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(f"{live_server}/login")
        await page.fill("input[name=username]", "teller1")
        await page.fill("input[name=password]", "testpass123")
        await page.click("input[type=submit]")
        await page.wait_for_url(f"{live_server}/main")

        work = page.frame(name="work")
        await work.fill("input[name=member_no]", "100007")
        await work.click("a:has-text('Search')")
        await page.wait_for_timeout(300)

        dob_handle = await work.locator("td:has-text('1978-04-17')").element_handle()
        assert dob_handle is not None
        box = await dob_handle.bounding_box()
        assert box is not None

        png_bytes = await mask_frame_region(page, "work", box)
        await browser.close()

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    cx, cy = int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2)
    # the masked DOB cell's center must be pure black
    assert img.getpixel((cx, cy)) == (0, 0, 0)
    # a point well outside the masked box (top-left corner of the whole
    # page, outside any frame content) must NOT have been touched
    assert img.getpixel((2, 2)) != (0, 0, 0)
