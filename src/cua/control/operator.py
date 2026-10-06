"""The human side of a handoff: attaching to the SAME live browser a
stuck discovery run is driving, via CDP — not a second, disconnected
browser. Playwright's `connect_over_cdp` is a second client to a
browser already running with `--remote-debugging-port`; it sees the
identical pages, frames and DOM state the agent was just looking at,
which is the whole point of a live-session handoff rather than a
"describe the problem and restart" escalation.
"""

from playwright.async_api import Browser, Page, Playwright

from cua.control.lease import ControlLease


async def attach(playwright: Playwright, cdp_url: str) -> Browser:
    """Connects to the already-running browser a stuck run is using."""
    return await playwright.chromium.connect_over_cdp(cdp_url)


def find_live_page(browser: Browser, *, url_contains: str) -> Page | None:
    """The operator doesn't get a page handle from the agent process (no
    shared Python state, see lease.py) — it finds the live page itself,
    by URL, among whatever the attached browser has open."""
    for context in browser.contexts:
        for page in context.pages:
            if url_contains in page.url:
                return page
    return None


def describe(lease: ControlLease) -> str:
    if lease.state == "agent":
        return "No handoff pending — the agent holds control."
    return f"Waiting for a human: {lease.reason!r}. Run `cua control release` when done."
