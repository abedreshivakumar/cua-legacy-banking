"""S11 acceptance: probe discovery for business outcomes, and relabel
drift. 999999 -> a probe discovery run reports business_outcome
member_not_found; the synthesized detector passes its negative control
against the real happy page, which hides that exact text in a
display:none div as a trap for an implementation that reads textContent
instead of visible text; a relabeled tenant still succeeds via a
label-independent fallback strategy, flagged as drifted in the trace."""

import os
import threading
import time
import urllib.request

import pytest
from playwright.async_api import async_playwright

from cua.artifact.store import capability_from_yaml
from cua.discovery.loop import run_discovery
from cua.discovery.model_client import FakeMessage, FakeToolUseBlock, ScriptedModelClient
from cua.discovery.outcome_probe import (
    ProbeError,
    passes_negative_control,
    synthesize_outcome_detector,
)
from cua.replay.checks import visible_page_text
from cua.replay.engine import replay

HOST = "127.0.0.1"
PORT = 8818
BASE_URL = f"http://{HOST}:{PORT}"
FIXTURE = "capabilities/member_inquiry/0.0.1.yaml"


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


@pytest.fixture(autouse=True)
def reset_faults():
    from target_app.app import faults

    faults.reset()
    yield
    faults.reset()


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


def _load(path: str):
    with open(path) as f:
        return capability_from_yaml(f.read())


async def _run_probe(page, member_no: str):
    work_frame = page.frame(name="work")
    member_box = await work_frame.locator("input[name=member_no]").bounding_box()
    search_box = await work_frame.locator("a:has-text('Search')").bounding_box()
    mx, my = member_box["x"] + member_box["width"] / 2, member_box["y"] + member_box["height"] / 2
    sx, sy = search_box["x"] + search_box["width"] / 2, search_box["y"] + search_box["height"] / 2

    turns = [
        FakeMessage(content=[_tool_use("left_click", {"coordinate": [mx, my]})]),
        FakeMessage(content=[_tool_use("type", {"text": member_no})]),
        FakeMessage(content=[_tool_use("left_click", {"coordinate": [sx, sy]})]),
        FakeMessage(
            content=[
                _tool_use(
                    "report_outcome",
                    {
                        "kind": "business_outcome",
                        "name": "member_not_found",
                        "rationale": "the results page says NO RECORD FOUND",
                    },
                    toolset=False,
                )
            ]
        ),
        FakeMessage(
            content=[
                _tool_use(
                    "goal_complete", {"summary": "Probed a non-existent member"}, toolset=False
                )
            ]
        ),
    ]
    client = ScriptedModelClient(turns=turns)
    return await run_discovery(page, client, f"Look up member {member_no}")


async def test_probe_discovery_reports_member_not_found(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await _run_probe(page, "999999")
        await browser.close()

    assert result.status == "completed"
    outcomes = [e for e in result.action_log if e.name == "report_outcome"]
    assert len(outcomes) == 1
    assert outcomes[0].input["name"] == "member_not_found"


async def test_synthesized_detector_passes_negative_control_on_real_happy_page(
    live_server: str,
) -> None:
    # The happy page hides "NO RECORD FOUND - RC=04" in a display:none div
    # (see target_app/templates/inquiry_result.html) specifically to trip
    # up a naive implementation that reads textContent instead of visible
    # text — a correct negative control must still pass.
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        probe_page = await _logged_in_page(browser, live_server)
        probe_result = await _run_probe(probe_page, "999999")
        probe_text = await visible_page_text(probe_page)
        await probe_page.close()

        happy_page = await _logged_in_page(browser, live_server)
        cap = _load(FIXTURE)
        happy_result = await replay(happy_page, cap, {"member_no": "100007"}, base_url=live_server)
        assert happy_result.status == "succeeded"
        happy_text = await visible_page_text(happy_page)

        detector = synthesize_outcome_detector(
            probe_result, probe_page_text=probe_text, happy_page_text=happy_text
        )
        assert detector.outcome == "member_not_found"
        assert "NO RECORD FOUND" in (detector.when.text or "")

        assert await passes_negative_control(happy_page, detector) is True
        await browser.close()


async def test_probe_without_a_reported_outcome_refuses_to_synthesize() -> None:
    from cua.discovery.loop import DiscoveryResult

    empty = DiscoveryResult(status="completed", summary="nothing reported")
    with pytest.raises(ProbeError):
        synthesize_outcome_detector(empty, probe_page_text="x", happy_page_text="y")


async def test_relabeled_tenant_still_succeeds_with_a_drift_flag(live_server: str) -> None:
    import urllib.parse

    data = urllib.parse.urlencode({"kind": "relabel"}).encode()
    req = urllib.request.Request(f"{live_server}/__faults", data=data, method="POST")
    urllib.request.urlopen(req)

    cap = _load(FIXTURE)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(page, cap, {"member_no": "100007"}, base_url=live_server)
        await browser.close()

    assert result.status == "succeeded"
    search_step = next(t for t in result.trace if t.step_id == "submit_search")
    assert search_step.strategy_used == "structural"
    assert search_step.drifted is True
    # the first step never referenced labels at all — no drift there
    member_no_step = next(t for t in result.trace if t.step_id == "enter_member_no")
    assert member_no_step.drifted is False
