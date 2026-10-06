"""S14 acceptance: a human can take over mid-run when discovery calls
request_human. The "human" here is a second Playwright client attaching
over CDP to the SAME already-running browser — not a fresh one — proving
a real live-session handoff, not just a state-machine simulation. After
the human releases the lease, discovery resumes and completes."""

import asyncio
import os
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from cua.control.lease import ControlLease
from cua.control.operator import attach, describe, find_live_page
from cua.discovery.loop import run_discovery
from cua.discovery.model_client import FakeMessage, FakeToolUseBlock, ScriptedModelClient

HOST = "127.0.0.1"
PORT = 8823
CDP_PORT = 9333
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


def _tool_use(name: str, input: dict, toolset: bool = True) -> FakeToolUseBlock:
    return FakeToolUseBlock(
        id=f"tu_{name}_{id(input)}",
        name=name,
        input=input,
        toolset_name="computer" if toolset else None,
    )


async def test_human_attaches_over_cdp_resumes_and_discovery_completes(
    live_server: str, tmp_path: Path
) -> None:
    lease = ControlLease(tmp_path / "lease.json")

    async with async_playwright() as pw:
        # The agent's own browser — launched with CDP exposed, exactly
        # like a real deployment would for handoff to even be possible.
        browser = await pw.chromium.launch(args=[f"--remote-debugging-port={CDP_PORT}"])
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(f"{BASE_URL}/login")
        await page.fill("input[name=username]", "teller1")
        await page.fill("input[name=password]", "testpass123")
        await page.click("input[type=submit]")
        await page.wait_for_url(f"{BASE_URL}/main")
        await page.wait_for_timeout(200)

        work_frame = page.frame(name="work")
        member_box = await work_frame.locator("input[name=member_no]").bounding_box()
        mx = member_box["x"] + member_box["width"] / 2
        my = member_box["y"] + member_box["height"] / 2

        turns = [
            FakeMessage(content=[_tool_use("left_click", {"coordinate": [mx, my]})]),
            FakeMessage(
                content=[
                    _tool_use(
                        "request_human",
                        {"reason": "not sure how to proceed, want a human to check"},
                        toolset=False,
                    )
                ]
            ),
            # The scripted "resumed" turn — what the model does once it's
            # told a human made changes and handed control back.
            FakeMessage(
                content=[
                    _tool_use(
                        "goal_complete",
                        {"summary": "human confirmed the form state, done"},
                        toolset=False,
                    )
                ]
            ),
        ]
        client = ScriptedModelClient(turns=turns)

        assert describe(lease) == "No handoff pending — the agent holds control."

        async def act_as_the_human() -> None:
            # Wait until the agent has actually handed off...
            while lease.state != "human":
                await page.wait_for_timeout(50)
            assert "human" in describe(lease)

            # ...then attach to the SAME live browser over CDP, exactly
            # as the `cua control` operator CLI would, and confirm it's
            # really the same session (same page, same DOM), not a
            # fresh one spun up independently.
            async with async_playwright() as operator_pw:
                operator_browser = await attach(operator_pw, f"http://{HOST}:{CDP_PORT}")
                live_page = find_live_page(operator_browser, url_contains="/main")
                assert live_page is not None
                operator_work = live_page.frame(name="work")
                value = await operator_work.locator("input[name=member_no]").input_value()
                assert value == ""  # confirms it's the live, pre-fill DOM state
                await operator_browser.close()

            lease.release_to_agent()

        human_task = asyncio.create_task(act_as_the_human())
        result = await run_discovery(
            page, client, "Look up a member", control_lease=lease, handoff_timeout_s=10
        )
        await human_task
        await browser.close()

    assert result.status == "completed"
    handoffs = [e for e in result.action_log if e.name == "human_handoff"]
    assert len(handoffs) == 1
    assert handoffs[0].input["resumed"] is True
