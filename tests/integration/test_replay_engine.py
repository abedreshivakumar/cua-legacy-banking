"""S6 acceptance: the hand-written artifact replays with seeded outputs,
distinguishes a business outcome from success, and rejects bad input —
with no model call and no `sleep` anywhere in replay/."""

import os
import threading
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from cua.artifact.store import capability_from_yaml
from cua.replay.engine import replay

FIXTURE = Path(__file__).parent.parent.parent / "capabilities" / "member_inquiry" / "0.0.1.yaml"

HOST = "127.0.0.1"
PORT = 8805
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


async def _logged_in_page(browser, base_url: str):
    page = await browser.new_page(viewport={"width": 1280, "height": 800})
    await page.goto(f"{base_url}/login")
    await page.fill("input[name=username]", "teller1")
    await page.fill("input[name=password]", "testpass123")
    await page.click("input[type=submit]")
    await page.wait_for_url(f"{base_url}/main")
    return page


async def test_replay_succeeds_with_seeded_outputs(live_server: str) -> None:
    capability = capability_from_yaml(FIXTURE.read_text())
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        result = await replay(page, capability, {"member_no": "100012"}, base_url=live_server)

        assert result.status == "succeeded"
        assert result.outputs["savings_balance"] == Decimal("1200.00")
        assert result.side_effects_committed == "none"
        assert len(result.trace) == 2  # enter_member_no, submit_search
        assert result.trace[0].strategy_used == "attr"

        await browser.close()


async def test_replay_returns_business_outcome_for_unknown_member(live_server: str) -> None:
    capability = capability_from_yaml(FIXTURE.read_text())
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        result = await replay(page, capability, {"member_no": "999999"}, base_url=live_server)

        assert result.status == "business_outcome"
        assert result.outcome == "member_not_found"

        await browser.close()


async def test_replay_rejects_input_not_matching_pattern(live_server: str) -> None:
    capability = capability_from_yaml(FIXTURE.read_text())
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        result = await replay(page, capability, {"member_no": "abc"}, base_url=live_server)

        assert result.status == "failed"
        assert result.code == "input_invalid"

        await browser.close()


async def test_replay_rejects_missing_input(live_server: str) -> None:
    capability = capability_from_yaml(FIXTURE.read_text())
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        result = await replay(page, capability, {}, base_url=live_server)

        assert result.status == "failed"
        assert result.code == "input_invalid"

        await browser.close()


def test_replay_package_never_imports_anthropic() -> None:
    replay_dir = Path(__file__).parent.parent.parent / "src" / "cua" / "replay"
    for path in replay_dir.glob("*.py"):
        text = path.read_text()
        assert "anthropic" not in text, f"{path} must not reference anthropic"


def test_replay_package_never_uses_sleep() -> None:
    replay_dir = Path(__file__).parent.parent.parent / "src" / "cua" / "replay"
    for path in replay_dir.glob("*.py"):
        text = path.read_text()
        assert "time.sleep" not in text, f"{path} must not block the event loop"
        assert "asyncio.sleep" not in text, f"{path} must poll via Playwright's own waits"
