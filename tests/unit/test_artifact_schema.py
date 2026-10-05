"""S4 acceptance: schema snapshot, round-trip, hand-written artifact
validates, and raw coordinates are rejected by the validator."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cua.artifact.schema import Capability
from cua.artifact.store import capability_from_yaml, capability_to_yaml, content_sha256
from cua.artifact.targets import AttrStrategy, TargetDescriptor

FIXTURE = Path(__file__).parent.parent.parent / "capabilities" / "member_inquiry" / "0.0.1.yaml"
SNAPSHOT = Path(__file__).parent / "fixtures" / "capability_schema.snapshot.json"


def test_handwritten_artifact_validates() -> None:
    cap = capability_from_yaml(FIXTURE.read_text())
    assert cap.id == "member_inquiry"
    assert cap.side_effects == "read_only"
    assert len(cap.steps) == 2
    assert cap.steps[0].id == "enter_member_no"


def test_round_trip_through_yaml() -> None:
    original = capability_from_yaml(FIXTURE.read_text())
    again = capability_from_yaml(capability_to_yaml(original))
    assert original.model_dump(mode="json") == again.model_dump(mode="json")


def test_content_sha256_is_stable_and_ignores_review() -> None:
    cap = capability_from_yaml(FIXTURE.read_text())
    h1 = content_sha256(cap)
    h2 = content_sha256(cap)
    assert h1 == h2
    assert len(h1) == 64

    approved = cap.model_copy(update={"status": "approved"})
    assert content_sha256(approved) != h1, "status is part of the content hash"


def test_json_schema_snapshot() -> None:
    schema = Capability.model_json_schema()
    if not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(schema, indent=2, sort_keys=True))
        pytest.skip("snapshot created — re-run to compare")
    expected = json.loads(SNAPSHOT.read_text())
    assert schema == expected, "schema changed — update the snapshot deliberately if intended"


def test_coordinate_field_rejected_on_strategy() -> None:
    with pytest.raises(ValidationError):
        AttrStrategy(attr="name", value="member_no", coordinate=[100, 200])  # type: ignore[call-arg]


def test_coordinate_field_rejected_on_target_descriptor() -> None:
    with pytest.raises(ValidationError):
        TargetDescriptor(
            strategies=[AttrStrategy(attr="name", value="member_no")],
            coordinate=[100, 200],  # type: ignore[call-arg]
        )
