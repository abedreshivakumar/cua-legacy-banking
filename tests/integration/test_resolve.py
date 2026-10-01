"""S5 acceptance: ranked-strategy resolution, and ambiguity never
falls back to a first-match guess."""

import os
import threading
import time
import urllib.request

import pytest
from playwright.async_api import async_playwright

from cua.artifact.targets import (
    AnchorStrategy,
    AttrStrategy,
    ElementExpectation,
    ScopeStep,
    TableCellStrategy,
    TargetDescriptor,
    TextStrategy,
)
from cua.surface.resolve import resolve

NO_LABELS: dict[str, str] = {}


@pytest.fixture
async def page():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        p = await browser.new_page()
        yield p
        await browser.close()


async def test_attr_strategy_resolves_uniquely(page) -> None:
    await page.set_content(
        '<table><tr><td>Member No.:</td><td><input name="member_no"></td></tr></table>'
    )
    target = TargetDescriptor(strategies=[AttrStrategy(attr="name", value="member_no")])
    res = await resolve(page, target, NO_LABELS)
    assert res.strategy_used == "attr"
    assert res.handle is not None


async def test_anchor_same_row_resolves_the_input_next_to_its_label(page) -> None:
    await page.set_content(
        '<table><tr><td>Member No.:</td><td><input type="text" class="x"></td></tr></table>'
    )
    target = TargetDescriptor(
        strategies=[
            AnchorStrategy(text="Member No.:", relation="same_row", control="textbox"),
        ]
    )
    res = await resolve(page, target, NO_LABELS)
    assert res.strategy_used == "anchor"
    tag = await res.handle.evaluate("el => el.tagName")
    assert tag == "INPUT"


async def test_table_cell_resolves_row_by_column_intersection(page) -> None:
    await page.set_content(
        """
        <table>
          <tr><th>Regular Savings</th><th>Available Balance</th></tr>
          <tr><td>Regular Savings</td><td>$ 123.45</td></tr>
        </table>
        """
    )
    target = TargetDescriptor(
        strategies=[
            TableCellStrategy(row_anchor="Regular Savings", column_header="Available Balance")
        ]
    )
    res = await resolve(page, target, NO_LABELS)
    assert res.strategy_used == "table_cell"
    text = await res.handle.evaluate("el => el.textContent")
    assert "123.45" in text


async def test_ambiguous_match_is_never_picked(page) -> None:
    await page.set_content("<button>Search</button><button>Search</button>")
    target = TargetDescriptor(strategies=[TextStrategy(text="Search", match="exact")])
    res = await resolve(page, target, NO_LABELS)
    assert res.handle is None
    assert res.attempts[0].matched == 2
    assert res.attempts[0].chosen is False
    assert res.attempts[0].error == "ambiguous"


async def test_ambiguity_falls_through_to_next_strategy() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content(
            "<button>Search</button><button>Search</button>"
            '<input name="go" type="hidden" value="search">'
        )
        target = TargetDescriptor(
            strategies=[
                TextStrategy(text="Search", match="exact"),  # ambiguous, 2 matches
                AttrStrategy(attr="name", value="go"),  # unique fallback
            ]
        )
        res = await resolve(page, target, NO_LABELS)
        assert res.strategy_used == "attr"
        assert res.attempts[0].error == "ambiguous"
        await browser.close()


async def test_forbidden_text_pattern_rejects_a_drifted_match(page) -> None:
    await page.set_content('<a href="#">Void</a>')
    target = TargetDescriptor(
        expect=ElementExpectation(forbidden_text_pattern=r"(?i)\bvoid\b"),
        strategies=[TextStrategy(text="Void", match="exact")],
    )
    res = await resolve(page, target, NO_LABELS)
    assert res.handle is None


async def test_editable_guard_skips_a_non_editable_match(page) -> None:
    await page.set_content('<span name="member_no">not an input</span>')
    target = TargetDescriptor(
        expect=ElementExpectation(editable=True),
        strategies=[AttrStrategy(attr="name", value="member_no")],
    )
    res = await resolve(page, target, NO_LABELS)
    assert res.handle is None


async def test_label_reference_is_substituted_before_matching(page) -> None:
    await page.set_content("<button>Find Member</button>")
    target = TargetDescriptor(strategies=[TextStrategy(text="$labels.nav_inquiry", match="exact")])
    res = await resolve(page, target, {"nav_inquiry": "Find Member"})
    assert res.handle is not None


# --- end-to-end against the real app: proves scope/frame resolution too ---

HOST = "127.0.0.1"
PORT = 8804
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


async def test_resolve_through_a_real_frame_scope(live_server: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        p = await browser.new_page(viewport={"width": 1280, "height": 800})
        await p.goto(f"{live_server}/login")
        await p.fill("input[name=username]", "teller1")
        await p.fill("input[name=password]", "testpass123")
        await p.click("input[type=submit]")
        await p.wait_for_url(f"{live_server}/main")
        await p.wait_for_timeout(200)

        target = TargetDescriptor(
            scope=[ScopeStep(name="work")],
            expect=ElementExpectation(kind="textbox", editable=True),
            strategies=[AttrStrategy(attr="name", value="member_no")],
        )
        res = await resolve(p, target, NO_LABELS)
        assert res.strategy_used == "attr"
        name = await res.handle.evaluate("el => el.name")
        assert name == "member_no"

        await browser.close()


async def test_table_cell_resolves_balance_on_the_real_result_page(live_server: str) -> None:
    """The same table_cell() bug the synthetic fixture caught (matching the
    header row instead of the data row) would also break this real path."""
    from target_app.data import LABELS_BASE

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        p = await browser.new_page(viewport={"width": 1280, "height": 800})
        await p.goto(f"{live_server}/login")
        await p.fill("input[name=username]", "teller1")
        await p.fill("input[name=password]", "testpass123")
        await p.click("input[type=submit]")
        await p.wait_for_url(f"{live_server}/main")

        work_frame = p.frame(name="work")
        await work_frame.fill("input[name=member_no]", "100007")
        await work_frame.click("a:has-text('Search')")
        await work_frame.wait_for_selector("text=Ivy Mockington")

        target = TargetDescriptor(
            scope=[ScopeStep(name="work")],
            strategies=[
                TableCellStrategy(
                    row_anchor="$labels.savings_row", column_header="$labels.balance_col"
                )
            ],
        )
        res = await resolve(p, target, LABELS_BASE)
        assert res.strategy_used == "table_cell"
        text = await res.handle.evaluate("el => el.textContent")
        assert "2345.67" in text

        await browser.close()
