"""S14: ControlLease state transitions and the async wait/release
handshake. No browser, no server — pure logic plus a timer."""

import asyncio
from pathlib import Path

import pytest

from cua.control.lease import ControlLease


def test_lease_defaults_to_agent_when_no_file_exists(tmp_path: Path) -> None:
    lease = ControlLease(tmp_path / "lease.json")
    assert lease.state == "agent"
    assert lease.reason is None


def test_hand_to_human_and_release_round_trip(tmp_path: Path) -> None:
    lease = ControlLease(tmp_path / "lease.json")
    lease.hand_to_human("stuck on a captcha-like interstitial")
    assert lease.state == "human"
    assert lease.reason == "stuck on a captcha-like interstitial"

    lease.release_to_agent()
    assert lease.state == "agent"
    assert lease.reason is None


async def test_wait_for_release_returns_true_once_a_second_handle_releases(
    tmp_path: Path,
) -> None:
    lease = ControlLease(tmp_path / "lease.json")
    lease.hand_to_human("manual fix needed")

    async def release_shortly() -> None:
        await asyncio.sleep(0.3)
        ControlLease(tmp_path / "lease.json").release_to_agent()

    release_task = asyncio.create_task(release_shortly())
    resumed = await lease.wait_for_release(timeout_s=5)
    await release_task

    assert resumed is True


async def test_wait_for_release_times_out_if_no_human_shows_up(tmp_path: Path) -> None:
    lease = ControlLease(tmp_path / "lease.json")
    lease.hand_to_human("nobody's watching")

    resumed = await lease.wait_for_release(timeout_s=0.3)

    assert resumed is False


@pytest.mark.parametrize("already", ["agent"])
async def test_wait_for_release_returns_immediately_if_already_agent(
    tmp_path: Path, already: str
) -> None:
    lease = ControlLease(tmp_path / "lease.json")
    # never handed to a human at all
    resumed = await lease.wait_for_release(timeout_s=0.05)
    assert resumed is True
