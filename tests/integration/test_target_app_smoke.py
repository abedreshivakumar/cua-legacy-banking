"""S2 acceptance: log in, search, and read a balance through nested frames."""

import os
import threading
import time
import urllib.request

import pytest
import uvicorn
from playwright.async_api import async_playwright

from target_app.app import app

HOST = "127.0.0.1"
PORT = 8800
BASE_URL = f"http://{HOST}:{PORT}"


@pytest.fixture(scope="module")
def live_server():
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


async def test_reads_balance_through_nested_frames(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        await page.goto(f"{live_server}/login")
        await page.fill("input[name=username]", "teller1")
        await page.fill("input[name=password]", "testpass123")
        await page.click("input[type=submit]")
        await page.wait_for_url(f"{live_server}/main")

        work_frame = page.frame(name="work")
        assert work_frame is not None
        await work_frame.fill("input[name=member_no]", "100007")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_selector("text=Ivy Mockington")

        balance_text = await work_frame.inner_text("body")
        assert "2345.67" in balance_text
        assert "MEMBER: 100007" in balance_text

        await browser.close()


async def test_unknown_member_shows_not_found(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        await page.goto(f"{live_server}/login")
        await page.fill("input[name=username]", "teller1")
        await page.fill("input[name=password]", "testpass123")
        await page.click("input[type=submit]")
        await page.wait_for_url(f"{live_server}/main")

        work_frame = page.frame(name="work")
        assert work_frame is not None
        await work_frame.fill("input[name=member_no]", "999999")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_selector("text=NO RECORD FOUND")

        await browser.close()
