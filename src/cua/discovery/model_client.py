"""The model client boundary: the real Anthropic client, or a
ScriptedModelClient that replays a fixture, with identical loop code
reading either one — see docs/DECISIONS.md on why no translation layer
is needed (both duck-type the same attributes the loop reads)."""

from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from cua.discovery.tools import COMPUTER_TOOLSET, DISCOVERY_TOOLS


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeThinkingBlock:
    text: str
    type: str = "thinking"


@dataclass
class FakeToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    toolset_name: str | None = None
    type: str = "tool_use"


@dataclass
class FakeMessage:
    content: list[Any]
    stop_reason: str = "tool_use"


class ModelClient(Protocol):
    async def next_turn(self, messages: list[dict]) -> Any: ...


class AnthropicModelClient:
    """The real client — never imported by replay/ (see docs/DECISIONS.md D9)."""

    def __init__(self, model: str = "claude-opus-5-5") -> None:
        self._client = anthropic.AsyncAnthropic()
        self._model = model

    async def next_turn(self, messages: list[dict]) -> Any:
        # Structurally valid per the SDK's own TypedDicts (verified directly
        # against the installed package before this was written — see
        # docs/DECISIONS.md "G0 spike"); mypy wants the exact TypedDict
        # imports rather than dict literals here, which isn't worth it for
        # a path our test suite never exercises (it's the real API call).
        return await self._client.messages.create(  # type: ignore[call-overload]
            model=self._model,
            max_tokens=2048,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": "high"},
            tools=[COMPUTER_TOOLSET, *DISCOVERY_TOOLS],
            messages=messages,
        )


@dataclass
class ScriptedModelClient:
    """Replays a fixed sequence of turns, in order, ignoring the messages
    actually sent — for offline tests only."""

    turns: list[FakeMessage]
    _i: int = field(default=0, init=False)

    async def next_turn(self, messages: list[dict]) -> FakeMessage:
        if self._i >= len(self.turns):
            raise IndexError("ScriptedModelClient ran out of fixture turns")
        turn = self.turns[self._i]
        self._i += 1
        return turn
