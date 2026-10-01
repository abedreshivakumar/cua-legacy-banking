"""A crash must never print local variables."""

import subprocess
import sys


def test_crash_does_not_leak_local_variables() -> None:
    sentinel = "SENTINEL_PASSWORD_DO_NOT_LEAK_8f3a1c"

    result = subprocess.run(
        [sys.executable, "-m", "cua.cli", "crash-test", sentinel],
        capture_output=True,
        text=True,
        cwd="src",
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert sentinel not in combined
    assert "RuntimeError" in combined
