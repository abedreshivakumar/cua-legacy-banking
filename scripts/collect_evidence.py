"""The evidence script (S15): runs discovery -> compile -> replay end to
end and writes a reviewable bundle under evidence/.

This run is OFFLINE — a ScriptedModelClient fixture standing in for the
API, zero model calls, same discipline as the rest of this repo's test
suite (see docs/DECISIONS.md D16). It demonstrates the full pipeline and
the evidence-writing tooling for real, but it is NOT the real live
LLM-driven discovery run the brief asks for in /evidence/ — that's a
separate, deliberately gated step (capped API spend, run once before
submitting). This script's output is clearly labeled as a demo run so
the two are never confused.

Run once: `uv run python scripts/collect_evidence.py`
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
from playwright.async_api import async_playwright

from cua.artifact.schema import AppBinding
from cua.artifact.store import capability_to_yaml
from cua.compile.compiler import compile_capability
from cua.discovery.loop import run_discovery
from cua.discovery.model_client import FakeMessage, FakeToolUseBlock, ScriptedModelClient
from cua.evidence.index import write_index
from cua.evidence.writer import copy_capability, write_replay_log, write_run_transcript
from cua.replay.engine import replay
from target_app.app import app

HOST = "127.0.0.1"
PORT = 8830
BASE_URL = f"http://{HOST}:{PORT}"
OUT_DIR = Path(__file__).parent.parent / "evidence" / "demo_member_inquiry"


def _tool_use(name: str, input: dict, toolset: bool = True) -> FakeToolUseBlock:
    return FakeToolUseBlock(
        id=f"tu_{name}_{id(input)}",
        name=name,
        input=input,
        toolset_name="computer" if toolset else None,
    )


def _start_target_app() -> uvicorn.Server:
    # `or` here, not setdefault: importing target_app.app above already ran
    # its own load_dotenv(), which sets COREBANK_PASSWORD to whatever .env
    # has — including an empty string if that's literally what's there.
    # setdefault only fills in a MISSING key, so it's a silent no-op for a
    # present-but-empty one (found the hard way: an emptied .env made this
    # script fail to log in with no indication why — see docs/DECISIONS.md).
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


async def _run_discovery(page):
    work_frame = page.frame(name="work")
    member_box = await work_frame.locator("input[name=member_no]").bounding_box()
    search_box = await work_frame.locator("a:has-text('Search')").bounding_box()
    mx = member_box["x"] + member_box["width"] / 2
    my = member_box["y"] + member_box["height"] / 2
    sx = search_box["x"] + search_box["width"] / 2
    sy = search_box["y"] + search_box["height"] / 2

    turns = [
        FakeMessage(content=[_tool_use("left_click", {"coordinate": [mx, my]})]),
        FakeMessage(content=[_tool_use("type", {"text": "100007"})]),
        FakeMessage(
            content=[
                _tool_use(
                    "declare_input",
                    {"name": "member_no", "value": "100007", "rationale": "the looked-up member"},
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
                        "rationale": "shown in the balance table",
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
    return await run_discovery(page, client, "Look up member 100007 and read their balance")


async def main() -> None:
    _start_target_app()
    # Filenames are run_id-keyed, so a rerun without this would just
    # accumulate stale files alongside the new ones rather than replacing
    # them — this bundle is a self-contained, regeneratable demo.
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()

        discovery_page = await _logged_in_page(browser)
        discovery_result = await _run_discovery(discovery_page)
        assert discovery_result.status == "completed", discovery_result.summary

        capability = compile_capability(
            discovery_result,
            capability_id="member_inquiry_demo",
            version="0.0.1",
            entry_route="/main",
            login_script_ref="scripts/corebank_login",
            app=AppBinding(vendor="mockbank", product="corebank_mock", version_range=">=0.1,<1"),
            model="scripted-fixture",
        )
        capability_tmp = OUT_DIR / "_capability_source.yaml"
        capability_tmp.write_text(capability_to_yaml(capability))

        replay_page = await _logged_in_page(browser)
        happy_result = await replay(
            replay_page, capability, {"member_no": "100007"}, base_url=BASE_URL
        )
        assert happy_result.status == "succeeded", happy_result

        await browser.close()

    transcript_path = write_run_transcript(discovery_result, OUT_DIR, sensitive_literals=["100007"])
    capability_path = copy_capability(capability, capability_tmp, OUT_DIR)
    capability_tmp.unlink()
    replay_log_path = write_replay_log(
        happy_result, OUT_DIR, label="happy_path", sensitive_literals=["100007"]
    )

    write_index(
        OUT_DIR,
        title="Evidence: member_inquiry (OFFLINE DEMO — not the required live LLM run)",
        discovery_result=discovery_result,
        transcript_path=transcript_path,
        capability_path=capability_path,
        replay_runs=[("happy path (member 100007)", happy_result, replay_log_path)],
    )

    print(f"Wrote evidence bundle to {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
