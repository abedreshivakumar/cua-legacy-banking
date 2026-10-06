"""S10 acceptance: the detector library + recovery handlers against the
real fault-injection app. interstitial -> resume_step; session_expire ->
restart_entry (actual relogin); http500/permission_denied -> hard failure;
commit_irreversible is never retried; the recovery budget is enforced."""

import os
import threading
import time
import urllib.request
from decimal import Decimal

import pytest
from playwright.async_api import Page, async_playwright

from cua.artifact.conditions import TextPresent
from cua.artifact.detector_library import corebank_mock_detectors
from cua.artifact.schema import (
    AppBinding,
    BackoffHandler,
    Capability,
    Checkpoint,
    Detector,
    Entry,
    PostCondition,
    Provenance,
    Step,
)
from cua.artifact.store import capability_from_yaml
from cua.artifact.targets import AttrStrategy, ElementExpectation, ScopeStep, TargetDescriptor
from cua.replay.engine import replay

HOST = "127.0.0.1"
PORT = 8814
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


def _register_fault(base_url: str, **fields: str) -> None:
    import urllib.parse

    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        f"{base_url}/__faults",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    urllib.request.urlopen(req)


async def _login_fn(page: Page) -> None:
    await page.goto(f"{BASE_URL}/login")
    await page.fill("input[name=username]", "teller1")
    await page.fill("input[name=password]", "testpass123")
    await page.click("input[type=submit]")
    await page.wait_for_url(f"{BASE_URL}/main")


async def _capability_with_library_detectors() -> Capability:
    with open(FIXTURE) as f:
        cap = capability_from_yaml(f.read())
    return cap.model_copy(update={"detectors": corebank_mock_detectors()})


async def test_interstitial_fault_recovers_via_resume_step(live_server: str) -> None:
    _register_fault(live_server, kind="interstitial", mode="once", routes="/fr/work/inq/result")
    cap = await _capability_with_library_detectors()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(
            page, cap, {"member_no": "100007"}, base_url=live_server, login_fn=_login_fn
        )
        await browser.close()

    assert result.status == "succeeded"
    assert result.outputs["savings_balance"] == Decimal("2345.67")
    assert result.recoveries == ["interstitial_notice"]


async def test_session_expire_fault_recovers_via_relogin_and_restart(live_server: str) -> None:
    _register_fault(live_server, kind="session_expire", mode="once", routes="/fr/work/inq/result")
    cap = await _capability_with_library_detectors()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(
            page, cap, {"member_no": "100007"}, base_url=live_server, login_fn=_login_fn
        )
        await browser.close()

    assert result.status == "succeeded"
    assert result.outputs["savings_balance"] == Decimal("2345.67")
    assert result.recoveries == ["session_expired"]


async def test_http500_fault_is_a_hard_failure(live_server: str) -> None:
    _register_fault(live_server, kind="http500", mode="once", routes="/fr/work/inq/result")
    cap = await _capability_with_library_detectors()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(
            page, cap, {"member_no": "100007"}, base_url=live_server, login_fn=_login_fn
        )
        await browser.close()

    assert result.status == "failed"
    assert result.code == "app_error"
    assert result.recoveries == []


async def test_permission_denied_fault_is_a_hard_failure(live_server: str) -> None:
    _register_fault(
        live_server, kind="permission_denied", mode="once", routes="/fr/work/inq/result"
    )
    cap = await _capability_with_library_detectors()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(
            page, cap, {"member_no": "100007"}, base_url=live_server, login_fn=_login_fn
        )
        await browser.close()

    assert result.status == "failed"
    assert result.code == "app_error"


def _single_step_capability(*, risk: str, detector_max_attempts: int = 1) -> Capability:
    """A minimal synthetic capability: one click step on the Search link,
    with a detector that ALWAYS matches (page title never goes away) —
    isolates the recovery-refusal/budget logic from any real fault."""
    target = TargetDescriptor(
        scope=[ScopeStep(name="work")],
        expect=ElementExpectation(kind="textbox", editable=True),
        strategies=[AttrStrategy(attr="name", value="member_no")],
    )
    always_true = TextPresent(scope=[ScopeStep(name="work")], text="MEMBER INQUIRY")
    step = Step(
        id="s1",
        intent="synthetic",
        action="click",
        target=target,
        risk=risk,  # type: ignore[arg-type]
        post=PostCondition(when=TextPresent(text="this never appears", scope=[]), timeout_ms=300),
        idempotent=(risk != "commit_irreversible"),
    )
    detector = Detector(
        id="always_on",
        kind="recoverable",
        when=always_true,
        active="always",
        priority=0,
        handler=BackoffHandler(wait_ms=10, then="retry_step"),
        max_attempts=detector_max_attempts,
        origin="library",
    )
    return Capability(
        id="synthetic",
        version="0.0.1",
        status="draft",
        summary="synthetic test capability",
        app=AppBinding(vendor="mockbank", product="corebank_mock", version_range=">=0.1,<1"),
        side_effects="irreversible_write" if risk == "commit_irreversible" else "read_only",
        entry=Entry(
            route="/main", login_script_ref="scripts/corebank_login", condition=always_true
        ),
        steps=[step],
        detectors=[detector],
        checkpoint=Checkpoint(when=always_true),
        provenance=Provenance(
            discovery_run_id="synthetic",
            model="n/a",
            recorded_at="2026-10-01T00:00:00Z",  # type: ignore[arg-type]
            transcript_sha256="0" * 64,
            compiler_version="0.0.1",
        ),
    )


async def test_commit_irreversible_step_refuses_retry(live_server: str) -> None:
    cap = _single_step_capability(risk="commit_irreversible")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(page, cap, {}, base_url=live_server, login_fn=_login_fn)
        await browser.close()

    assert result.status == "failed"
    assert result.code == "recovery_exhausted"
    assert "commit_irreversible" in result.expected


async def test_recovery_budget_is_enforced(live_server: str) -> None:
    # max_attempts well above the global budget, so the GLOBAL cap trips first.
    cap = _single_step_capability(risk="query", detector_max_attempts=10)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(page, cap, {}, base_url=live_server, login_fn=_login_fn)
        await browser.close()

    assert result.status == "failed"
    assert result.code == "recovery_exhausted"
    assert "whole run" in result.expected
    assert len(result.recoveries) == 5  # MAX_RUN_RECOVERIES


async def _logged_in_page(browser, base_url: str) -> Page:
    page = await browser.new_page(viewport={"width": 1280, "height": 800})
    await page.goto(f"{base_url}/login")
    await page.fill("input[name=username]", "teller1")
    await page.fill("input[name=password]", "testpass123")
    await page.click("input[type=submit]")
    await page.wait_for_url(f"{base_url}/main")
    await page.wait_for_timeout(200)
    return page
