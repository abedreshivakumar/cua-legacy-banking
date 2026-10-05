"""S7 acceptance: the discovery loop against a real browser and the real
target app, with a ScriptedModelClient standing in for the API — zero
LLM calls, fully offline."""

import os
import threading
import time
import urllib.request

import pytest
from playwright.async_api import async_playwright

from cua.discovery.loop import run_discovery
from cua.discovery.model_client import (
    FakeMessage,
    FakeTextBlock,
    FakeToolUseBlock,
    ScriptedModelClient,
)

HOST = "127.0.0.1"
PORT = 8812
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
    await page.wait_for_timeout(200)
    return page


def _tool_use(name: str, input: dict, toolset: bool = True) -> FakeToolUseBlock:
    return FakeToolUseBlock(
        id=f"tu_{name}_{id(input)}",
        name=name,
        input=input,
        toolset_name="computer" if toolset else None,
    )


async def test_discovery_completes_a_member_lookup(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        work_frame = page.frame(name="work")
        member_box = await work_frame.locator("input[name=member_no]").bounding_box()
        search_box = await work_frame.locator("a:has-text('Search')").bounding_box()
        mx, my = (
            member_box["x"] + member_box["width"] / 2,
            member_box["y"] + member_box["height"] / 2,
        )
        sx, sy = (
            search_box["x"] + search_box["width"] / 2,
            search_box["y"] + search_box["height"] / 2,
        )

        turns = [
            FakeMessage(content=[_tool_use("left_click", {"coordinate": [mx, my]})]),
            FakeMessage(content=[_tool_use("type", {"text": "100007"})]),
            FakeMessage(
                content=[
                    _tool_use(
                        "declare_input",
                        {
                            "name": "member_no",
                            "value": "100007",
                            "rationale": "the looked-up member",
                        },
                        toolset=False,
                    )
                ]
            ),
            FakeMessage(content=[_tool_use("left_click", {"coordinate": [sx, sy]})]),
            FakeMessage(
                content=[
                    _tool_use(
                        "record_output",
                        {
                            "name": "savings_balance",
                            "value": "2345.67",
                            "rationale": "shown in the table",
                        },
                        toolset=False,
                    )
                ]
            ),
            FakeMessage(
                content=[
                    _tool_use(
                        "goal_complete", {"summary": "Found member 100007's balance"}, toolset=False
                    )
                ]
            ),
        ]
        client = ScriptedModelClient(turns=turns)

        result = await run_discovery(page, client, "Look up member 100007 and read their balance")

        assert result.status == "completed"
        assert "100007" in result.summary
        member_actions = [e for e in result.action_log if e.kind == "member_action"]
        assert [e.name for e in member_actions] == ["left_click", "type", "left_click"]
        # the first click must have resolved to the real member_no input
        assert member_actions[0].resolved["name"] == "member_no"

        await browser.close()


async def test_batch_staleness_skips_remaining_actions_after_navigation(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        work_frame = page.frame(name="work")
        search_box = await work_frame.locator("a:has-text('Search')").bounding_box()
        sx, sy = (
            search_box["x"] + search_box["width"] / 2,
            search_box["y"] + search_box["height"] / 2,
        )

        # one turn with TWO actions: the click navigates (empty member_no ->
        # not-found page), so the second action must be skipped as stale.
        turns = [
            FakeMessage(
                content=[
                    _tool_use("left_click", {"coordinate": [sx, sy]}),
                    _tool_use("type", {"text": "should not run"}),
                ]
            ),
            FakeMessage(content=[_tool_use("goal_complete", {"summary": "done"}, toolset=False)]),
        ]
        client = ScriptedModelClient(turns=turns)

        result = await run_discovery(page, client, "irrelevant for this test")

        assert result.status == "completed"
        # tool_results for the batch turn are in messages[2] ("user" after turn 1)
        batch_results = result.messages[2]["content"]
        assert batch_results[0]["content"] != "screen changed; re-observe"
        assert batch_results[1].get("is_error") is True
        assert batch_results[1]["content"] == "screen changed; re-observe"

        await browser.close()


async def test_prose_only_end_turn_nudges_then_dead_ends(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        turns = [
            FakeMessage(
                content=[FakeTextBlock(text="I'm thinking about this.")], stop_reason="end_turn"
            ),
            FakeMessage(content=[FakeTextBlock(text="Still thinking.")], stop_reason="end_turn"),
        ]
        client = ScriptedModelClient(turns=turns)

        result = await run_discovery(page, client, "irrelevant for this test")

        assert result.status == "dead_end"
        # one nudge was sent: user, assistant, user(nudge), assistant = 4 messages
        assert len(result.messages) == 4
        assert "Continue using tools" in result.messages[2]["content"][0]["text"]

        await browser.close()


async def test_refusal_escalates_immediately(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        turns = [
            FakeMessage(content=[FakeTextBlock(text="can't help with that")], stop_reason="refusal")
        ]
        client = ScriptedModelClient(turns=turns)

        result = await run_discovery(page, client, "irrelevant for this test")

        assert result.status == "escalated"
        assert result.summary == "model refused"

        await browser.close()


async def test_history_is_append_only(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        turns = [
            FakeMessage(content=[_tool_use("screenshot", {})]),
            FakeMessage(content=[_tool_use("goal_complete", {"summary": "done"}, toolset=False)]),
        ]
        client = ScriptedModelClient(turns=turns)

        result = await run_discovery(page, client, "the original goal text")

        # the very first message (the goal) is never touched
        assert result.messages[0] == {
            "role": "user",
            "content": [{"type": "text", "text": "the original goal text"}],
        }
        # messages only ever grew — never shrank or got reordered mid-run.
        # turn 1 (screenshot): assistant + its tool_result. turn 2
        # (goal_complete): assistant + its own tool_result, appended before
        # returning, so the trail is complete.
        assert len(result.messages) == 5
        assert [m["role"] for m in result.messages] == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
        ]

        await browser.close()
