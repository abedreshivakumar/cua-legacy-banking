"""Custom strict tools the discovery model calls alongside the computer
toolset, plus the toolset's own tool entry."""

COMPUTER_TOOLSET: dict = {"type": "computer_toolset_20260801"}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "strict": True,
    }


DISCOVERY_TOOLS: list[dict] = [
    _tool(
        "declare_input",
        "Mark a value you are about to type as a reusable parameter, not a literal.",
        {
            "name": {"type": "string"},
            "value": {"type": "string"},
            "rationale": {"type": "string"},
        },
        ["name", "value", "rationale"],
    ),
    _tool(
        "record_output",
        "Mark a value you just read on screen as a named output to extract on replay.",
        {
            "name": {"type": "string"},
            "value": {"type": "string"},
            "rationale": {"type": "string"},
        },
        ["name", "value", "rationale"],
    ),
    _tool(
        "assert_checkpoint",
        "Declare that the current screen confirms the goal was reached.",
        {"description": {"type": "string"}},
        ["description"],
    ),
    _tool(
        "report_outcome",
        "Report a business or error outcome this screen represents, e.g. 'record not found'.",
        {
            "kind": {
                "type": "string",
                "enum": ["business_outcome", "recoverable", "hard_failure"],
            },
            "name": {"type": "string"},
            "rationale": {"type": "string"},
        },
        ["kind", "name", "rationale"],
    ),
    _tool(
        "request_human",
        "Stop and ask a human to take over, because you cannot safely proceed.",
        {"reason": {"type": "string"}},
        ["reason"],
    ),
    _tool(
        "goal_complete",
        "Declare the goal finished and stop.",
        {"summary": {"type": "string"}},
        ["summary"],
    ),
]
