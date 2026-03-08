"""
OpenAI adapter — OpenAI API with streaming.
Requires: pip install openai
"""
import logging
import os
import traceback
from typing import Generator

from adapter.base import AgentAdapter, AgentMessage, AgentResponse, AdapterState
from utils.app_logger import AppLogger


class OpenAIAdapter(AgentAdapter):
    """
    Adapter for OpenAI's API (GPT-4o, etc.).
    Supports streaming responses with function calling state detection.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o",
        system_prompt: str = "You are a helpful voice assistant. Keep responses concise and conversational. Do not use markdown, lists, or formatting — speak naturally as in a conversation.",
        max_tokens: int = 1024,
    ):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._client = None
        self._should_stop = False

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
            self.logger.info(f"OpenAI client initialized for model: {self._model}")
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")

    def send(self, message: str, context: list[AgentMessage] | None = None) -> Generator[AgentResponse, None, None]:
        self._should_stop = False

        try:
            self._ensure_client()
        except Exception as e:
            self.logger.error(f"Failed to initialize client: {e}")
            yield AgentResponse(text="OpenAI API is not configured.", state=AdapterState.ERROR)
            return

        # Build messages — context already includes the current user message
        messages = [{"role": "system", "content": self._system_prompt}]
        if context:
            for msg in context:
                if msg.role in ("user", "assistant"):
                    messages.append({"role": msg.role, "content": msg.text})
        else:
            messages.append({"role": "user", "content": message})

        yield AgentResponse(text="", state=AdapterState.THINKING)

        try:
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=self._max_tokens,
                stream=True,
            )

            for chunk in stream:
                if self._should_stop:
                    yield AgentResponse(text="", state=AdapterState.DONE)
                    return

                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield AgentResponse(text=content, state=AdapterState.SPEAKING)

            yield AgentResponse(text="", state=AdapterState.DONE)

        except Exception as e:
            self.logger.error(f"OpenAI API error: {e}, {traceback.format_exc()}")
            yield AgentResponse(text="I had trouble reaching OpenAI.", state=AdapterState.ERROR)

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
        return "openai"

    @property
    def description(self) -> str:
        return f"OpenAI API ({self._model})"
