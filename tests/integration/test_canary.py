"""S13 acceptance: the canary. A discovery run is seeded with a plausible
real leak path — the model's own "thinking" narrating an on-screen value
verbatim, which happens routinely with a real LLM and isn't something
record_output/declare_input gate at all — then the run is written to an
evidence transcript on disk, and every seeded sensitive value (a DOB
pattern-caught generically, and the queried member number caught only
because it's declared sensitive) must have zero hits anywhere under the
output root."""

import os
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from cua.discovery.loop import run_discovery
from cua.discovery.model_client import (
    FakeMessage,
    FakeThinkingBlock,
    FakeToolUseBlock,
    ScriptedModelClient,
)
from cua.evidence.writer import write_run_transcript

HOST = "127.0.0.1"
PORT = 8822
BASE_URL = f"http://{HOST}:{PORT}"
SEEDED_DOB = "1978-04-17"
SEEDED_MEMBER_NO = "100007"


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


async def test_canary_zero_hits_for_seeded_sensitive_values(
    live_server: str, tmp_path: Path
) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        work_frame = page.frame(name="work")
        member_box = await work_frame.locator("input[name=member_no]").bounding_box()
        search_box = await work_frame.locator("a:has-text('Search')").bounding_box()
        mx = member_box["x"] + member_box["width"] / 2
        my = member_box["y"] + member_box["height"] / 2
        sx = search_box["x"] + search_box["width"] / 2
        sy = search_box["y"] + search_box["height"] / 2

        turns = [
            FakeMessage(content=[_tool_use("left_click", {"coordinate": [mx, my]})]),
            FakeMessage(content=[_tool_use("type", {"text": SEEDED_MEMBER_NO})]),
            FakeMessage(
                content=[
                    _tool_use(
                        "declare_input",
                        {"name": "member_no", "value": SEEDED_MEMBER_NO, "rationale": "looked up"},
                        toolset=False,
                    )
                ]
            ),
            FakeMessage(content=[_tool_use("left_click", {"coordinate": [sx, sy]})]),
            # A real LLM narrates what it sees — including the DOB, which
            # nothing in the tool schema ever asked it to declare. This is
            # the realistic leak path a canary has to actually catch.
            FakeMessage(
                content=[
                    FakeThinkingBlock(
                        text=(
                            f"I can see member {SEEDED_MEMBER_NO}'s record, born "
                            f"{SEEDED_DOB}, with an active savings balance."
                        )
                    ),
                    _tool_use(
                        "record_output",
                        {"name": "savings_balance", "value": "2345.67", "rationale": "shown"},
                        toolset=False,
                    ),
                ]
            ),
            FakeMessage(content=[_tool_use("goal_complete", {"summary": "done"}, toolset=False)]),
        ]
        client = ScriptedModelClient(turns=turns)
        result = await run_discovery(page, client, f"Look up member {SEEDED_MEMBER_NO}")
        await browser.close()

    assert result.status == "completed"
    thinking_entries = [e for e in result.action_log if e.kind == "thinking"]
    # the leak really is in there — otherwise this test proves nothing
    assert any(SEEDED_DOB in (e.text or "") for e in thinking_entries)

    out_dir = tmp_path / "evidence"
    write_run_transcript(result, out_dir, sensitive_literals=[SEEDED_MEMBER_NO])

    for path in out_dir.rglob("*"):
        if path.is_file():
            content = path.read_text()
            assert SEEDED_DOB not in content, f"DOB leaked into {path}"
            assert SEEDED_MEMBER_NO not in content, f"member_no leaked into {path}"
