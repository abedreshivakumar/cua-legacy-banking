"""S12 acceptance: the act() network choke point and the commit-approval
gate. off-origin and javascript: requests are blocked outright; a plain
POST (member search) is unaffected; a read_only capability can never
commit even if it tries; a write-capable capability needs a matching
approval record — none -> blocked_pending_approval, one -> succeeds with
a receipt and consumes it, reusing the same (now-consumed) record -> a
hard policy_denied, not a second approval."""

import contextlib
import os
import threading
import time
import urllib.request

import pytest
from playwright.async_api import Page, async_playwright

from cua.artifact.conditions import TextPresent
from cua.artifact.schema import PostCondition, Step
from cua.artifact.store import capability_from_yaml
from cua.replay.engine import replay
from cua.replay.steps import run_action
from cua.safety.approval import ApprovalStore, approval_key
from cua.safety.policy import PolicyConfig

HOST = "127.0.0.1"
PORT = 8815
BASE_URL = f"http://{HOST}:{PORT}"
INQUIRY_FIXTURE = "capabilities/member_inquiry/0.0.1.yaml"
TRANSFER_FIXTURE = "capabilities/transfer_funds/0.0.1.yaml"
COMMIT_ROUTES = ["/fr/work/xfer/receipt"]


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


async def _login_fn(page: Page) -> None:
    await page.goto(f"{BASE_URL}/login")
    await page.fill("input[name=username]", "teller1")
    await page.fill("input[name=password]", "testpass123")
    await page.click("input[type=submit]")
    await page.wait_for_url(f"{BASE_URL}/main")


async def _logged_in_page(browser, base_url: str) -> Page:
    page = await browser.new_page(viewport={"width": 1280, "height": 800})
    await page.goto(f"{base_url}/login")
    await page.fill("input[name=username]", "teller1")
    await page.fill("input[name=password]", "testpass123")
    await page.click("input[type=submit]")
    await page.wait_for_url(f"{base_url}/main")
    await page.wait_for_timeout(200)
    return page


def _load(path: str):
    with open(path) as f:
        return capability_from_yaml(f.read())


async def test_off_origin_navigation_is_blocked(live_server: str) -> None:
    cap = _load(INQUIRY_FIXTURE)
    # Redirect entry to an off-origin URL to exercise the guard directly,
    # without needing a discovered step that happens to navigate off-site.
    cap = cap.model_copy(update={"entry": cap.entry.model_copy(update={"route": "/main"})})
    policy = PolicyConfig(allowed_origins=[live_server], commit_routes=COMMIT_ROUTES)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        from cua.safety.policy import PolicyState, install_policy_guard

        state = PolicyState()
        await install_policy_guard(
            page, policy, state, side_effects="read_only", decide_commit=None
        )
        with contextlib.suppress(Exception):
            await page.goto("https://example.com/", timeout=3000)
        await browser.close()

    assert state.latest() is not None
    assert state.latest().kind == "off_origin"


async def test_javascript_scheme_navigate_is_blocked(live_server: str) -> None:
    # A javascript: URI never produces a network request (confirmed
    # directly — page.route never fires for one), so the network guard in
    # safety/policy.py can't see it — this is refused earlier, in
    # run_action's navigate branch, before the goto. Scoped to the explicit
    # `navigate` action only: blanket-blocking every javascript: href
    # encountered while clicking would also break the mock app's own
    # legitimate link-triggered-submit pattern (found by hitting it).
    step = Step(
        id="s1",
        intent="synthetic",
        action="navigate",
        value="javascript:window.__hit=1",
        risk="navigate",
        post=PostCondition(when=TextPresent(text="unused", scope=[]), timeout_ms=300),
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content("<html><body>start</body></html>")
        strategy_used, act_error = await run_action(page, step, {}, {})
        await browser.close()

    assert act_error is not None
    assert act_error["code"] == "policy_denied"


async def test_post_member_search_is_unaffected_by_policy(live_server: str) -> None:
    cap = _load(INQUIRY_FIXTURE)
    policy = PolicyConfig(allowed_origins=[live_server], commit_routes=COMMIT_ROUTES)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(
            page,
            cap,
            {"member_no": "100007"},
            base_url=live_server,
            login_fn=_login_fn,
            policy=policy,
        )
        await browser.close()

    assert result.status == "succeeded"
    assert result.side_effects_committed == "none"


async def test_read_only_capability_cannot_commit(live_server: str) -> None:
    cap = _load(TRANSFER_FIXTURE).model_copy(update={"side_effects": "read_only"})
    policy = PolicyConfig(allowed_origins=[live_server], commit_routes=COMMIT_ROUTES)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(
            page,
            cap,
            {"amount": "50.00"},
            base_url=live_server,
            login_fn=_login_fn,
            policy=policy,
        )
        await browser.close()

    assert result.status == "failed"
    assert result.code == "policy_denied"
    assert "commit_blocked_read_only" in result.observed


async def test_transfer_without_approval_is_blocked_pending(live_server: str) -> None:
    cap = _load(TRANSFER_FIXTURE)
    policy = PolicyConfig(allowed_origins=[live_server], commit_routes=COMMIT_ROUTES)
    store = ApprovalStore()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(
            page,
            cap,
            {"amount": "50.00"},
            base_url=live_server,
            login_fn=_login_fn,
            policy=policy,
            approval_store=store,
        )
        await browser.close()

    assert result.status == "blocked_pending_approval"


async def test_transfer_with_approval_succeeds_and_consumes_it(live_server: str) -> None:
    cap = _load(TRANSFER_FIXTURE)
    policy = PolicyConfig(allowed_origins=[live_server], commit_routes=COMMIT_ROUTES)
    store = ApprovalStore()

    from cua.artifact.store import content_sha256

    key = approval_key(cap.id, cap.version, content_sha256(cap), {"amount": "50.00"})
    store.grant(key)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result = await replay(
            page,
            cap,
            {"amount": "50.00"},
            base_url=live_server,
            login_fn=_login_fn,
            policy=policy,
            approval_store=store,
        )
        await browser.close()

    assert result.status == "succeeded"
    assert result.side_effects_committed == "yes"
    assert result.outputs["confirmation_no"].startswith("CNF")

    # Reusing the SAME (now-consumed) record for a second replay attempt
    # is a hard denial, not a fresh pending-approval state.
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser, live_server)
        result2 = await replay(
            page,
            cap,
            {"amount": "50.00"},
            base_url=live_server,
            login_fn=_login_fn,
            policy=policy,
            approval_store=store,
        )
        await browser.close()

    assert result2.status == "failed"
    assert result2.code == "policy_denied"
    assert "commit_reused_approval" in result2.observed
