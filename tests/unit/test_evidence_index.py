"""S15: INDEX.md generation. Pure logic — constructs a DiscoveryResult
and RunResult directly, no browser or server."""

from pathlib import Path

from cua.discovery.loop import ActionLogEntry, DiscoveryResult
from cua.evidence.index import write_index
from cua.replay.result import Succeeded


def _succeeded() -> Succeeded:
    return Succeeded(
        run_id="r1",
        capability="member_inquiry",
        version="0.0.1",
        effective_sha256="0" * 64,
        outputs={"savings_balance": "2345.67"},
    )


def test_write_index_lists_every_section_when_all_are_present(tmp_path: Path) -> None:
    discovery = DiscoveryResult(
        status="completed",
        summary="done",
        action_log=[ActionLogEntry(step=1, kind="member_action", name="left_click", input={})],
        run_id="d1",
    )
    transcript = tmp_path / "d1.transcript.txt"
    transcript.write_text("...")
    capability_file = tmp_path / "member_inquiry-0.0.1.yaml"
    capability_file.write_text("id: member_inquiry")
    replay_log = tmp_path / "happy.r1.replay.json"
    replay_log.write_text("{}")

    index_path = write_index(
        tmp_path,
        title="Evidence: member inquiry",
        discovery_result=discovery,
        transcript_path=transcript,
        capability_path=capability_file,
        replay_runs=[("happy path", _succeeded(), replay_log)],
    )

    content = index_path.read_text()
    assert "# Evidence: member inquiry" in content
    assert "`d1`" in content
    assert "d1.transcript.txt" in content
    assert "member_inquiry-0.0.1.yaml" in content
    assert "happy path" in content
    assert "status=`succeeded`" in content
    assert "happy.r1.replay.json" in content


def test_write_index_omits_sections_that_are_none(tmp_path: Path) -> None:
    index_path = write_index(tmp_path, title="Empty bundle")
    content = index_path.read_text()
    assert content.strip() == "# Empty bundle"
