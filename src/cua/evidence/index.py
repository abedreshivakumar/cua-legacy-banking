"""Generating INDEX.md for an evidence bundle — what's in this folder
and how to read it, so a reviewer doesn't have to guess which file is
which or run anything to understand what happened.
"""

from pathlib import Path

from cua.discovery.loop import DiscoveryResult
from cua.replay.result import RunResult


def write_index(
    out_dir: Path,
    *,
    title: str,
    discovery_result: DiscoveryResult | None = None,
    transcript_path: Path | None = None,
    capability_path: Path | None = None,
    replay_runs: list[tuple[str, RunResult, Path]] | None = None,
    screenshots: list[tuple[str, Path]] | None = None,
) -> Path:
    lines = [f"# {title}", ""]

    if discovery_result is not None:
        lines.append("## Discovery run")
        lines.append(f"- run_id: `{discovery_result.run_id}`")
        lines.append(f"- status: `{discovery_result.status}`")
        lines.append(f"- actions logged: {len(discovery_result.action_log)}")
        if transcript_path is not None:
            lines.append(f"- transcript: [{transcript_path.name}](./{transcript_path.name})")
        lines.append("")

    if capability_path is not None:
        lines.append("## Compiled artifact")
        lines.append(f"- [{capability_path.name}](./{capability_path.name})")
        lines.append("")

    if replay_runs:
        lines.append("## Replay runs (deterministic, zero model calls)")
        for label, result, log_path in replay_runs:
            detail = f"status=`{result.status}`"
            code = getattr(result, "code", None)
            if code is not None:
                detail += f", code=`{code}`"
            outcome = getattr(result, "outcome", None)
            if outcome is not None:
                detail += f", outcome=`{outcome}`"
            lines.append(
                f"- **{label}**: {detail}, run_id=`{result.run_id}`, "
                f"side_effects_committed=`{result.side_effects_committed}` — "
                f"[{log_path.name}](./{log_path.name})"
            )
        lines.append("")

    if screenshots:
        lines.append("## Screenshots")
        for label, path in screenshots:
            lines.append(f"- **{label}**: [{path.name}](./{path.name})")
        lines.append("")

    path = out_dir / "INDEX.md"
    path.write_text("\n".join(lines))
    return path
