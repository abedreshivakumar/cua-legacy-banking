"""CUA command-line entry point."""

import typer

app = typer.Typer(
    name="cua",
    help="Discover a legacy UI flow once with an LLM; replay it deterministically forever after.",
    pretty_exceptions_show_locals=False,  # never print local vars (may hold secrets) on crash
)


@app.command()
def version() -> None:
    """Print the CUA version."""
    typer.echo("cua 0.1.0")


@app.command(name="crash-test", hidden=True)
def _crash_test(secret: str) -> None:
    """Raise with a secret-shaped local in scope, for the no-locals-leak test."""
    sensitive_local = secret  # noqa: F841 — intentionally unused; crash test needs it in scope
    raise RuntimeError("deliberate crash for the no-locals-leak test")


if __name__ == "__main__":
    app()
