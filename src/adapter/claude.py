"""
Claude adapter — Anthropic API with streaming.
Requires: pip install anthropic
"""
import logging
import os
import traceback
from typing import Generator

from adapter.base import AgentAdapter, AgentMessage, AgentResponse, AdapterState
from utils.app_logger import AppLogger


class ClaudeAdapter(AgentAdapter):
    """
    Adapter for Anthropic's Claude API.
    Supports streaming responses with tool_use state detection.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-sonnet-4-20250514",
        system_prompt: str = "You are a helpful voice assistant. Keep responses concise and conversational. Do not use markdown, lists, or formatting — speak naturally as in a conversation.",
        max_tokens: int = 1024,
    ):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._client = None
        self._should_stop = False

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
            self.logger.info(f"Anthropic client initialized for model: {self._model}")
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")

    def send(self, message: str, context: list[AgentMessage] | None = None) -> Generator[AgentResponse, None, None]:
        self._should_stop = False

        try:
            self._ensure_client()
        except Exception as e:
            self.logger.error(f"Failed to initialize client: {e}")
            yield AgentResponse(text="Claude API is not configured.", state=AdapterState.ERROR)
            return

        # Build messages — context already includes the current user message
        messages = []
        if context:
            for msg in context:
                if msg.role in ("user", "assistant"):
                    messages.append({"role": msg.role, "content": msg.text})
        else:
            messages.append({"role": "user", "content": message})

        yield AgentResponse(text="", state=AdapterState.THINKING)

        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system_prompt,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    if self._should_stop:
                        yield AgentResponse(text="", state=AdapterState.DONE)
                        return
                    if text:
                        yield AgentResponse(text=text, state=AdapterState.SPEAKING)

            yield AgentResponse(text="", state=AdapterState.DONE)

        except Exception as e:
            self.logger.error(f"Claude API error: {e}, {traceback.format_exc()}")
            yield AgentResponse(text="I had trouble reaching Claude.", state=AdapterState.ERROR)

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            self._ensure_client()
            return True
        except Exception:
            return False

    def stop(self) -> None:
        self._should_stop = True

    def cleanup(self) -> None:
        self._client = None

    @property
    def name(self) -> str:
        return "claude"

    @property
    def description(self) -> str:
        return f"Anthropic Claude API ({self._model})"
