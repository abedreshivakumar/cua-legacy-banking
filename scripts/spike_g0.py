"""G0 spike (dev-only, not part of the deliverable surface): a capped live
run proving the computer toolset + frame-aware hit-test actually work
together before anything else gets built on top of that assumption.

Hard-capped at 6 model turns. Run once: `uv run python scripts/spike_g0.py`
"""

import asyncio
import base64
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for `target_app`

import anthropic
import uvicorn
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from cua.surface.hittest import hit_test
from target_app.app import app

HOST = "127.0.0.1"
PORT = 8803
BASE_URL = f"http://{HOST}:{PORT}"
MAX_STEPS = 6
LOG_DIR = Path(__file__).parent.parent / "runs" / "g0_spike"


def start_target_app() -> uvicorn.Server:
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


async def execute_action(page, name: str, raw_input: dict) -> tuple[str | None, dict | None]:
    """Run one member action. Returns (screenshot_b64_if_any, resolved_facts_if_any)."""
    if name == "screenshot":
        png = await page.screenshot()
        return base64.b64encode(png).decode(), None

    if name in ("left_click", "double_click", "right_click", "triple_click"):
        coord = raw_input.get("coordinate", [0, 0])
        x, y = coord[0], coord[1]
        facts = await hit_test(page, x, y)
        await page.mouse.click(x, y)
        return None, facts

    if name == "type":
        await page.keyboard.type(raw_input.get("text", ""))
        return None, None

    if name == "key":
        await page.keyboard.press(raw_input.get("text", ""))
        return None, None

    if name == "wait":
        await page.wait_for_timeout(500)
        return None, None

    return None, {"unsupported_action": name}


async def main() -> None:
    load_dotenv()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{int(time.time())}.jsonl"

    server = start_target_app()
    client = anthropic.AsyncAnthropic()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # Login is scripted, outside the model loop (D3) — the model never
        # sees credentials.
        await page.goto(f"{BASE_URL}/login")
        await page.fill("input[name=username]", "teller1")
        await page.fill("input[name=password]", "testpass123")
        await page.click("input[type=submit]")
        await page.wait_for_url(f"{BASE_URL}/main")
        await page.wait_for_timeout(300)

        goal = (
            "You are looking at a legacy banking teller application, shown via "
            "screenshots. Find the member number field, type 100007 into it, "
            "then click the control that submits the search. Once member "
            "details are visible, say DONE and stop."
        )
        messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": goal}]}]

        with log_path.open("w") as log:
            clicks_resolved_in_frame = 0
            for step in range(1, MAX_STEPS + 1):
                try:
                    response = await client.messages.create(
                        model="claude-opus-5-5",
                        max_tokens=2048,
                        thinking={"type": "adaptive", "display": "summarized"},
                        output_config={"effort": "high"},
                        tools=[{"type": "computer_toolset_20260801"}],
                        messages=messages,
                    )
                except anthropic.APIStatusError as e:
                    print(f"STEP {step}: API ERROR {e.status_code}: {e.message}")
                    log.write(json.dumps({"step": step, "error": str(e)}) + "\n")
                    break

                messages.append({"role": "assistant", "content": response.content})
                print(f"STEP {step}: stop_reason={response.stop_reason}")

                if response.stop_reason == "refusal":
                    print("  refused — escalating (expected behavior, stopping spike)")
                    break

                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if not tool_use_blocks:
                    for b in response.content:
                        if b.type == "text":
                            print(f"  final text: {b.text[:200]}")
                    break

                tool_results = []
                for block in tool_use_blocks:
                    print(f"  action={block.name} input={block.input}")
                    screenshot_b64, facts = await execute_action(page, block.name, block.input)
                    if facts and facts.get("framePath"):
                        clicks_resolved_in_frame += 1
                        print(f"    resolved -> {facts}")
                    log.write(
                        json.dumps(
                            {
                                "step": step,
                                "action": block.name,
                                "input": block.input,
                                "resolved": facts,
                            }
                        )
                        + "\n"
                    )

                    if screenshot_b64:
                        content = [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64,
                                },
                            }
                        ]
                    else:
                        content = "OK"
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "toolset_name": block.toolset_name,
                            "content": content,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})

        final_text = await page.frame(name="work").inner_text("body")
        print("\n--- final work-frame text ---")
        print(final_text[:500])
        print(f"\nclicks resolved into a nested frame: {clicks_resolved_in_frame}")
        print(f"log written to {log_path}")

        await browser.close()

    server.should_exit = True


if __name__ == "__main__":
    asyncio.run(main())
