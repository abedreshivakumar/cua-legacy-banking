"""S2 acceptance: every fault mode is toggleable via POST /__faults."""

import os
import threading
import time
import urllib.request

import pytest
import uvicorn
from playwright.async_api import async_playwright

from target_app.app import app, faults

HOST = "127.0.0.1"
PORT = 8801
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


@pytest.fixture(autouse=True)
def reset_faults():
    faults.reset()
    yield
    faults.reset()


async def _login_and_get_work_frame(live_server: str, page):
    await page.goto(f"{live_server}/login")
    await page.fill("input[name=username]", "teller1")
    await page.fill("input[name=password]", "testpass123")
    await page.click("input[type=submit]")
    await page.wait_for_url(f"{live_server}/main")
    return page.frame(name="work")


def _register_fault(live_server: str, **fields) -> None:
    data = "&".join(f"{k}={v}" for k, v in fields.items())
    req = urllib.request.Request(
        f"{live_server}/__faults",
        data=data.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    urllib.request.urlopen(req)


async def test_interstitial_fault_shows_system_notice(live_server: str) -> None:
    _register_fault(live_server, kind="interstitial", mode="once", routes="/fr/work/inq/result")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        work_frame = await _login_and_get_work_frame(live_server, page)
        await work_frame.fill("input[name=member_no]", "100007")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_selector("text=SYSTEM NOTICE")
        await browser.close()


async def test_http500_fault_returns_error_page(live_server: str) -> None:
    _register_fault(live_server, kind="http500", mode="once", routes="/fr/work/inq/result")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        work_frame = await _login_and_get_work_frame(live_server, page)
        await work_frame.fill("input[name=member_no]", "100007")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_selector("text=SYSTEM ERROR")
        await browser.close()


async def test_permission_denied_fault_returns_403_page(live_server: str) -> None:
    _register_fault(
        live_server, kind="permission_denied", mode="once", routes="/fr/work/inq/result"
    )
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        work_frame = await _login_and_get_work_frame(live_server, page)
        await work_frame.fill("input[name=member_no]", "100007")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_selector("text=ACCESS DENIED")
        await browser.close()


async def test_once_mode_fires_exactly_once(live_server: str) -> None:
    _register_fault(live_server, kind="http500", mode="once", routes="/fr/work/inq/result")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        work_frame = await _login_and_get_work_frame(live_server, page)

        await work_frame.fill("input[name=member_no]", "100007")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_selector("text=SYSTEM ERROR")

        await work_frame.goto(f"{live_server}/fr/work/inq")
        await work_frame.fill("input[name=member_no]", "100007")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_selector("text=Ivy Mockington")

        await browser.close()


async def test_session_expire_fault_forces_relogin(live_server: str) -> None:
    _register_fault(live_server, kind="session_expire", mode="nth:1", routes="/fr/work/inq/result")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        work_frame = await _login_and_get_work_frame(live_server, page)

        await work_frame.fill("input[name=member_no]", "100007")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_url(f"{live_server}/login")

        await browser.close()


async def test_relabel_fault_swaps_labels(live_server: str) -> None:
    _register_fault(live_server, kind="relabel", mode="always", routes="")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        work_frame = await _login_and_get_work_frame(live_server, page)
        text = await work_frame.inner_text("body")
        assert "Acct Holder ID" in text
        await browser.close()
