"""S9 acceptance: compile a completed discovery run into a Capability,
then prove the whole discover -> compile -> replay loop actually works —
fully offline, via ScriptedModelClient. This is a rehearsal of the G3
proving milestone's checks, without spending any API credit."""

import os
import re
import threading
import time
import urllib.request
from decimal import Decimal

import pytest
from playwright.async_api import async_playwright

from cua.artifact.schema import AppBinding
from cua.artifact.store import capability_to_yaml, content_sha256
from cua.compile.compiler import CompileError, compile_capability
from cua.discovery.loop import ActionLogEntry, DiscoveryResult, run_discovery
from cua.discovery.model_client import FakeMessage, FakeToolUseBlock, ScriptedModelClient
from cua.replay.engine import replay

HOST = "127.0.0.1"
PORT = 8813
BASE_URL = f"http://{HOST}:{PORT}"

APP = AppBinding(vendor="mockbank", product="corebank_mock", version_range=">=0.1,<1")


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


async def _discover_member_lookup(page, member_no: str = "100007") -> DiscoveryResult:
    work_frame = page.frame(name="work")
    member_box = await work_frame.locator("input[name=member_no]").bounding_box()
    search_box = await work_frame.locator("a:has-text('Search')").bounding_box()
    mx, my = member_box["x"] + member_box["width"] / 2, member_box["y"] + member_box["height"] / 2
    sx, sy = search_box["x"] + search_box["width"] / 2, search_box["y"] + search_box["height"] / 2

    turns = [
        FakeMessage(content=[_tool_use("left_click", {"coordinate": [mx, my]})]),
        FakeMessage(content=[_tool_use("type", {"text": member_no})]),
        FakeMessage(
            content=[
                _tool_use(
                    "declare_input",
                    {"name": "member_no", "value": member_no, "rationale": "looked-up member"},
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
                    "goal_complete",
                    {"summary": f"Found member {member_no}'s balance"},
                    toolset=False,
                )
            ]
        ),
    ]
    client = ScriptedModelClient(turns=turns)
    return await run_discovery(page, client, f"Look up member {member_no} and read their balance")


async def test_compile_happy_path_produces_valid_capability(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await _discover_member_lookup(page)
        await browser.close()

    assert result.status == "completed"
    cap = compile_capability(
        result,
        capability_id="member_inquiry_discovered",
        version="0.1.0",
        entry_route="/main",
        login_script_ref="scripts/corebank_login",
        app=APP,
        model="claude-opus-5-5",
    )

    assert cap.status == "draft"
    assert len(cap.steps) == 3
    assert [s.action for s in cap.steps] == ["click", "type", "click"]
    assert cap.inputs[0].name == "member_no"
    assert cap.outputs[0].name == "savings_balance"
    assert cap.side_effects == "read_only"
    assert cap.provenance.discovery_run_id == result.run_id
    assert cap.steps[1].value == "{{ inputs.member_no }}"
    # the `type` step inherits the preceding click's target (it has none
    # of its own — it types into whatever that click focused).
    assert cap.steps[1].target == cap.steps[0].target
    # every secondary-field validity check the schema itself enforces
    # (extra="forbid", semver, etc.) already ran via Capability(...) above.


async def test_compile_fails_on_literal_without_declare_input(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)

        work_frame = page.frame(name="work")
        member_box = await work_frame.locator("input[name=member_no]").bounding_box()
        mx, my = (
            member_box["x"] + member_box["width"] / 2,
            member_box["y"] + member_box["height"] / 2,
        )

        turns = [
            FakeMessage(content=[_tool_use("left_click", {"coordinate": [mx, my]})]),
            FakeMessage(content=[_tool_use("type", {"text": "100007"})]),  # no declare_input!
            FakeMessage(content=[_tool_use("goal_complete", {"summary": "done"}, toolset=False)]),
        ]
        result = await run_discovery(page, ScriptedModelClient(turns=turns), "irrelevant")
        await browser.close()

    assert result.status == "completed"
    with pytest.raises(CompileError, match="literals are deny-by-default"):
        compile_capability(
            result,
            capability_id="x",
            version="0.1.0",
            entry_route="/main",
            login_script_ref="scripts/corebank_login",
            app=APP,
            model="claude-opus-5-5",
        )


async def test_compile_fails_on_unresolved_target(live_server: str) -> None:
    result = DiscoveryResult(
        status="completed",
        summary="done",
        action_log=[
            ActionLogEntry(
                step=1,
                kind="member_action",
                name="left_click",
                input={"coordinate": [1, 1]},
                target=None,
            )
        ],
    )
    with pytest.raises(CompileError, match="no resolved target"):
        compile_capability(
            result,
            capability_id="x",
            version="0.1.0",
            entry_route="/main",
            login_script_ref="scripts/corebank_login",
            app=APP,
            model="claude-opus-5-5",
        )


async def test_compiled_capability_self_replays_on_a_different_input(live_server: str) -> None:
    """The core proof: discover on 100007, compile, replay on a DIFFERENT
    member (100012) with zero model calls, and get the right answer."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        discover_page = await _logged_in_page(browser, live_server)
        result = await _discover_member_lookup(discover_page, member_no="100007")
        await discover_page.close()

        cap = compile_capability(
            result,
            capability_id="member_inquiry_discovered",
            version="0.1.0",
            entry_route="/main",
            login_script_ref="scripts/corebank_login",
            app=APP,
            model="claude-opus-5-5",
        )

        replay_page = await _logged_in_page(browser, live_server)
        replay_result = await replay(
            replay_page, cap, {"member_no": "100012"}, base_url=live_server
        )
        await browser.close()

    assert replay_result.status == "succeeded"
    assert replay_result.outputs["savings_balance"] == Decimal("1200.00")

    # G3-style checks, offline: no RAW coordinate pairs (resolved_from:
    # coordinate is legitimate provenance — it names HOW the target was
    # found, not a pixel position) and no literal from the discovery run,
    # leaked into the artifact. Every Strategy.by is one of the ranked
    # kinds (attr/role/anchor/table_cell/text/structural/visual) per the
    # schema's discriminated union — "a raw coordinate" isn't even an
    # expressible value, which is the structural guarantee D12 describes.
    yaml_text = capability_to_yaml(cap)
    assert re.search(r"coordinate:\s*\[", yaml_text) is None
    assert "100007" not in yaml_text
    assert len(content_sha256(cap)) == 64


def test_replay_package_still_imports_no_anthropic() -> None:
    import pathlib

    replay_dir = pathlib.Path(__file__).parent.parent.parent / "src" / "cua" / "replay"
    for path in replay_dir.glob("*.py"):
        assert "anthropic" not in path.read_text()
