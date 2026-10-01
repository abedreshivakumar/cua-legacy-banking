"""Hit-testing must resolve a coordinate to the right element through frames,
before we ever spend a model call trusting it."""

import os
import threading
import time
import urllib.request

import pytest
from playwright.async_api import async_playwright

from cua.surface.hittest import hit_test
from target_app.app import app

HOST = "127.0.0.1"
PORT = 8802
BASE_URL = f"http://{HOST}:{PORT}"


@pytest.fixture(scope="module")
def live_server():
    import uvicorn

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


async def test_hit_test_resolves_into_nested_frame_input(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        await page.goto(f"{live_server}/login")
        await page.fill("input[name=username]", "teller1")
        await page.fill("input[name=password]", "testpass123")
        await page.click("input[type=submit]")
        await page.wait_for_url(f"{live_server}/main")
        await page.wait_for_timeout(200)  # let child frames finish loading

        work_frame = page.frame(name="work")
        assert work_frame is not None
        box = await work_frame.locator("input[name=member_no]").bounding_box()
        assert box is not None

        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        facts = await hit_test(page, cx, cy)

        assert facts is not None
        assert facts["tag"] == "INPUT"
        assert facts["name"] == "member_no"
        assert facts["framePath"] == ["work"]

        await browser.close()
