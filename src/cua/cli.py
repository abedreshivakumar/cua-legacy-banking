"""CUA command-line entry point."""

import asyncio
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from cua.artifact.store import capability_from_yaml
from cua.control.lease import ControlLease
from cua.control.operator import describe
from cua.replay.engine import replay as run_replay
from cua.replay.result import RunResult

app = typer.Typer(
    name="cua",
    help="Discover a legacy UI flow once with an LLM; replay it deterministically forever after.",
    pretty_exceptions_show_locals=False,  # never print local vars (may hold secrets) on crash
)
control_app = typer.Typer(help="Operator-side commands for a live-session handoff.")
app.add_typer(control_app, name="control")


@app.command()
def version() -> None:
    """Print the CUA version."""
    typer.echo("cua 0.1.0")


async def _replay_async(
    capability_path: Path, inputs: dict[str, str], base_url: str, headed: bool
) -> RunResult:
    load_dotenv()
    capability = capability_from_yaml(capability_path.read_text())
    user = os.environ.get("COREBANK_USER", "teller1")
    password = os.environ.get("COREBANK_PASSWORD", "")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # Login is scripted, never part of the artifact or a model call.
        await page.goto(f"{base_url}/login")
        await page.fill("input[name=username]", user)
        await page.fill("input[name=password]", password)
        await page.click("input[type=submit]")
        await page.wait_for_url(f"{base_url}/main")

        result = await run_replay(page, capability, inputs, base_url=base_url)
        await browser.close()
    return result


@app.command()
def replay(
    capability_path: Path = typer.Argument(..., help="Path to a compiled capability YAML"),
    input: list[str] = typer.Option([], "--input", "-i", help="key=value, repeatable"),
    base_url: str = typer.Option("http://127.0.0.1:8800", "--base-url"),
    headed: bool = typer.Option(False, "--headed", help="Show the browser instead of headless"),
) -> None:
    """Replay a compiled capability against a live target app. No model call."""
    parsed_inputs = dict(kv.split("=", 1) for kv in input)
    result = asyncio.run(_replay_async(capability_path, parsed_inputs, base_url, headed))
    typer.echo(result.model_dump_json(indent=2))
    if result.status not in ("succeeded", "business_outcome"):
        raise typer.Exit(code=1)


_DEFAULT_LEASE_PATH = Path(".cua/control_lease.json")


@control_app.command("status")
def control_status(
    lease_path: Path = typer.Option(_DEFAULT_LEASE_PATH, "--lease-path"),
) -> None:
    """Show whether a discovery run is currently waiting for a human."""
    typer.echo(describe(ControlLease(lease_path)))


@control_app.command("release")
def control_release(
    lease_path: Path = typer.Option(_DEFAULT_LEASE_PATH, "--lease-path"),
) -> None:
    """Hand control back to the agent after making whatever fix was needed."""
    lease = ControlLease(lease_path)
    if lease.state != "human":
        typer.echo("Nothing to release — the agent already holds control.")
        raise typer.Exit(code=1)
    lease.release_to_agent()
    typer.echo("Released — the agent will resume on its next poll.")


@app.command(name="crash-test", hidden=True)
def _crash_test(secret: str) -> None:
    """Raise with a secret-shaped local in scope, for the no-locals-leak test."""
    sensitive_local = secret  # noqa: F841 — intentionally unused; crash test needs it in scope
    raise RuntimeError("deliberate crash for the no-locals-leak test")


if __name__ == "__main__":
    app()
