from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Generator


class AdapterState(str, Enum):
    """States an adapter can report back — mapped to UI colors by the shell."""
    THINKING = "thinking"
    SPEAKING = "speaking"
    TOOL_CALLING = "tool_calling"
    DONE = "done"
    ERROR = "error"
    IDLE = "idle"


@dataclass
class AgentMessage:
    """A single message in the conversation context."""
    text: str
    role: str  # "user", "assistant", "system", "tool_result"
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResponse:
    """A streamed chunk from an adapter — text + current state."""
    text: str
    state: AdapterState
    metadata: dict = field(default_factory=dict)


class AgentAdapter(ABC):
    """
    The protocol every agent backend must implement.

    Adapters encapsulate all backend complexity (tool calling, MCP, function calling, etc.)
    and expose a simple streaming interface: send text in, get text + state out.
    """

    @abstractmethod
    def send(self, message: str, context: list[AgentMessage] | None = None) -> Generator[AgentResponse, None, None]:
        """Send a user message, yield streaming responses with state updates."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Health check — can this adapter handle requests right now?"""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Interrupt current processing."""
        ...

    def cleanup(self) -> None:
        """Release resources. Override if needed."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name."""
        ...

    @property
    def description(self) -> str:
        """Optional description of the adapter's capabilities."""
        return ""
