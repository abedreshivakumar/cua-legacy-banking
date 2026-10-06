"""Extends evidence/live_member_inquiry/ with a replay that hits an
exceptional state, and a screenshot captured at that point.

Deliberately reuses the capability ALREADY compiled by
scripts/collect_evidence_live.py's one real discovery run — this makes
zero additional API calls. It replays the same artifact with a member
number that doesn't exist. That capability was compiled from a single
happy-path discovery run and carries no business-outcome detector (see
docs/DECISIONS.md D24/S11) — the live run collect_evidence_live.py
produced never went through probe discovery — so this deliberately
surfaces as a hard failure (postcondition_timeout: the click-Search
step's own post-condition, which only knows to wait for the balance
table, never resolves on a "not found" page), not a clean
business_outcome. That's an honest, correct result given what this
artifact actually knows, and exactly the kind of exceptional-state
replay the brief asks evidence to include.

Run once: `uv run python scripts/extend_live_evidence.py`
"""

import asyncio
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for `target_app`

import uvicorn
from playwright.async_api import async_playwright
from pydantic import TypeAdapter

from cua.artifact.store import capability_from_yaml
from cua.evidence.index import write_index
from cua.evidence.writer import write_replay_log, write_screenshot
from cua.replay.engine import replay
from cua.replay.result import RunResult
from target_app.app import app

_RESULT_ADAPTER: TypeAdapter = TypeAdapter(RunResult)

HOST = "127.0.0.1"
PORT = 8832
BASE_URL = f"http://{HOST}:{PORT}"
OUT_DIR = Path(__file__).parent.parent / "evidence" / "live_member_inquiry"
BAD_MEMBER_NO = "999999"


def _start_target_app() -> uvicorn.Server:
    # `or`, not setdefault — see scripts/collect_evidence.py for why.
    os.environ["COREBANK_USER"] = os.environ.get("COREBANK_USER") or "teller1"
    os.environ["COREBANK_PASSWORD"] = os.environ.get("COREBANK_PASSWORD") or "testpass123"
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{BASE_URL}/__health", timeout=0.2)
            return server
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("target app did not start in time")


async def _logged_in_page(browser):
    page = await browser.new_page(viewport={"width": 1280, "height": 800})
    await page.goto(f"{BASE_URL}/login")
    await page.fill("input[name=username]", "teller1")
    await page.fill("input[name=password]", "testpass123")
    await page.click("input[type=submit]")
    await page.wait_for_url(f"{BASE_URL}/main")
    await page.wait_for_timeout(200)
    return page


async def main() -> None:
    capability_files = sorted(OUT_DIR.glob("member_inquiry_live-*.yaml"))
    if not capability_files:
        raise RuntimeError(
            f"no compiled capability found in {OUT_DIR} — run "
            "scripts/collect_evidence_live.py first"
        )
    capability = capability_from_yaml(capability_files[0].read_text())
    input_name = capability.inputs[0].name

    _start_target_app()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await _logged_in_page(browser)

        error_result = await replay(
            page, capability, {input_name: BAD_MEMBER_NO}, base_url=BASE_URL
        )
        print(f"error-path replay status: {error_result.status}")
        assert error_result.status == "failed", (
            f"expected a hard failure for a nonexistent member, got {error_result.status}"
        )

        screenshot_bytes = await page.screenshot()
        await browser.close()

    error_log_path = write_replay_log(
        error_result, OUT_DIR, label="error_path", sensitive_literals=[BAD_MEMBER_NO]
    )
    screenshot_path = write_screenshot(screenshot_bytes, OUT_DIR, label="error_path_screenshot")

    # Rebuild INDEX.md from scratch with both replay runs + the screenshot —
    # write_index always regenerates the whole file, so this isn't additive
    # on top of the previous one, it replaces it with the fuller picture.
    happy_logs = sorted(OUT_DIR.glob("happy_path.*.replay.json"))
    happy_result = None
    if happy_logs:
        happy_result = _RESULT_ADAPTER.validate_python(json.loads(happy_logs[0].read_text()))

    replay_runs = []
    if happy_result is not None:
        replay_runs.append(
            ("happy path (replay of the compiled artifact)", happy_result, happy_logs[0])
        )
    replay_runs.append(
        (f"error path (member {BAD_MEMBER_NO} does not exist)", error_result, error_log_path)
    )

    transcript_files = sorted(OUT_DIR.glob("*.transcript.txt"))

    # write_index regenerates the whole file, so the discovery summary from
    # the original run has to be reconstructed here too, not dropped — its
    # header lines are exactly "run_id: X" / "status: Y", written by
    # write_run_transcript in the first place.
    discovery_summary = None
    if transcript_files:
        lines = transcript_files[0].read_text().splitlines()
        header = {ln.split(": ", 1)[0]: ln.split(": ", 1)[1] for ln in lines[:2]}
        action_count = sum(1 for ln in lines if ln.startswith("[step "))
        discovery_summary = SimpleNamespace(
            run_id=header["run_id"], status=header["status"], action_log=[None] * action_count
        )

    write_index(
        OUT_DIR,
        title="Evidence: member_inquiry — REAL live claude-opus-5-5 discovery run",
        discovery_result=discovery_summary,
        transcript_path=transcript_files[0] if transcript_files else None,
        capability_path=capability_files[0],
        replay_runs=replay_runs,
        screenshots=[("error path — results page", screenshot_path)],
    )

    print(f"Extended evidence bundle at {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
