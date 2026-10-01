"""Load/save a Capability as YAML; compute its content hash for approval."""

import hashlib
import json

import yaml

from cua.artifact.schema import Capability


def capability_from_yaml(text: str) -> Capability:
    data = yaml.safe_load(text)
    return Capability.model_validate(data)


def capability_to_yaml(cap: Capability) -> str:
    data = cap.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def content_sha256(cap: Capability) -> str:
    """Hash everything except provenance and review — approval is bound to
    what the capability DOES, not to who recorded or approved it."""
    data = cap.model_dump(mode="json", exclude={"provenance", "review"})
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
