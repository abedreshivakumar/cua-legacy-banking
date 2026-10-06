"""The REAL evidence script: a genuine live `claude-opus-5-5` discovery
run (the computer-use toolset, real API calls, real cost) against the
real mock app, then the same deterministic compile -> replay -> write
pipeline as the offline demo (scripts/collect_evidence.py).

This is the actual deliverable the brief asks for in /evidence/ — run
once, deliberately, after explicit go-ahead to spend API credit (same
gating as scripts/spike_g0.py). Capped at MAX_STEPS turns as a cost
backstop; the G0 spike needed 3.

Run once: `uv run python scripts/collect_evidence_live.py`
"""

import asyncio
import os
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for `target_app`

import uvicorn
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from cua.artifact.schema import AppBinding
from cua.artifact.store import capability_to_yaml
from cua.compile.compiler import compile_capability
from cua.discovery.loop import run_discovery
from cua.discovery.model_client import AnthropicModelClient
from cua.evidence.index import write_index
from cua.evidence.writer import copy_capability, write_replay_log, write_run_transcript
from cua.replay.engine import replay
from target_app.app import app

HOST = "127.0.0.1"
PORT = 8831
BASE_URL = f"http://{HOST}:{PORT}"
OUT_DIR = Path(__file__).parent.parent / "evidence" / "live_member_inquiry"
MAX_STEPS = 10
MEMBER_NO = "100007"


def _start_target_app() -> uvicorn.Server:
    os.environ.setdefault("COREBANK_USER", "teller1")
    os.environ.setdefault("COREBANK_PASSWORD", "testpass123")
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
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set — this script makes real API calls")

    _start_target_app()
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()

        discovery_page = await _logged_in_page(browser)
        client = AnthropicModelClient(model="claude-opus-5-5")
        discovery_result = await run_discovery(
            discovery_page,
            client,
            f"Look up member {MEMBER_NO} in the member inquiry screen and record their "
            "Regular Savings balance as an output. Declare the member number you type as "
            "a reusable input before you type it.",
            max_steps=MAX_STEPS,
        )
        print(f"discovery status: {discovery_result.status} — {discovery_result.summary}")
        assert discovery_result.status == "completed", (
            f"live discovery did not complete: {discovery_result.status} — "
            f"{discovery_result.summary}"
        )

        capability = compile_capability(
            discovery_result,
            capability_id="member_inquiry_live",
            version="0.0.1",
            entry_route="/main",
            login_script_ref="scripts/corebank_login",
            app=AppBinding(vendor="mockbank", product="corebank_mock", version_range=">=0.1,<1"),
            model="claude-opus-5-5",
        )
        capability_tmp = OUT_DIR / "_capability_source.yaml"
        capability_tmp.write_text(capability_to_yaml(capability))
        print(f"compiled capability: {capability.id} ({len(capability.steps)} steps)")

        # Deterministic replay of the JUST-compiled artifact — zero
        # additional model calls, proving discover -> compile -> replay
        # works end to end on a real live run, not just on fixtures. The
        # input's name is whatever the model itself chose via
        # declare_input (a real live run isn't bound to this script's own
        # fixture-test naming conventions — found the hard way when a
        # first attempt hardcoded "member_no" and the model had actually
        # named it "member_number"; see docs/DECISIONS.md D30), so it's
        # read off the compiled capability rather than assumed.
        assert len(capability.inputs) == 1, capability.inputs
        replay_page = await _logged_in_page(browser)
        happy_result = await replay(
            replay_page,
            capability,
            {capability.inputs[0].name: MEMBER_NO},
            base_url=BASE_URL,
        )
        print(f"replay status: {happy_result.status}")
        assert happy_result.status == "succeeded", happy_result

        await browser.close()

    transcript_path = write_run_transcript(
        discovery_result, OUT_DIR, sensitive_literals=[MEMBER_NO]
    )
    capability_path = copy_capability(capability, capability_tmp, OUT_DIR)
    capability_tmp.unlink()
    replay_log_path = write_replay_log(
        happy_result, OUT_DIR, label="happy_path", sensitive_literals=[MEMBER_NO]
    )

    write_index(
        OUT_DIR,
        title="Evidence: member_inquiry — REAL live claude-opus-5-5 discovery run",
        discovery_result=discovery_result,
        transcript_path=transcript_path,
        capability_path=capability_path,
        replay_runs=[("replay of the compiled artifact", happy_result, replay_log_path)],
    )

    print(f"Wrote evidence bundle to {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
