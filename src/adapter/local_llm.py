"""
Local LLM adapter — wraps the existing llama.cpp inference server.
Reuses LlamaCppServer and AVAILABLE_MODELS from the existing codebase.
"""
import json
import logging
import traceback
from typing import Generator

import requests

from adapter.base import AgentAdapter, AgentMessage, AgentResponse, AdapterState
from utils.app_logger import AppLogger

# Lazy-loaded to avoid module-level model file validation in inference.py
_inference_module = None


def _get_inference():
    global _inference_module
    if _inference_module is None:
        import importlib
        _inference_module = importlib.import_module("llm.inference")
    return _inference_module


def get_available_models() -> dict:
    return _get_inference().AVAILABLE_MODELS


class LocalLLMAdapter(AgentAdapter):
    """
    Adapter for local llama.cpp models.
    Manages the server lifecycle and streams responses via OpenAI-compatible API.
    """

    def __init__(
        self,
        model_name: str = "Qwen3-0.6B-abliterated-Q4_K_S",
        system_prompt: str = "You are a helpful voice assistant. Keep responses concise and conversational. Never repeat greetings or introductions — go straight to answering the question. Do not use emojis.",
        host: str = "127.0.0.1",
        port: int = 8080,
    ):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self._model_name = model_name
        self._system_prompt = system_prompt
        self._server = None
        self._should_stop = False
        self._host = host
        self._port = port

    def _ensure_server(self) -> None:
        """Start the server if not already running."""
        if self._server and self._server.is_running():
            return

        inf = _get_inference()
        available = inf.AVAILABLE_MODELS

        if self._model_name not in available:
            raise ValueError(f"Model '{self._model_name}' not found. Available: {list(available.keys())}")

        model_config = available[self._model_name].copy()
        model_config["args"] = model_config.get("args", {}).copy()
        model_config["args"]["host"] = self._host
        model_config["args"]["port"] = self._port

        self._server = inf.LlamaCppServer(model_config)
        self._server.start(silent=True)
        self.logger.info(f"Started local LLM server: {self._model_name}")

        # Wait for the server to be fully ready for chat completions
        import time
        for _ in range(10):
            try:
                r = requests.post(
                    f"http://{self._server.host}:{self._server.port}/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                    timeout=3,
                )
                if r.status_code == 200:
                    self.logger.info("Server fully ready for inference.")
                    return
            except Exception:
                pass
            time.sleep(0.5)
        self.logger.warning("Server started but may not be fully warmed up.")

    def send(self, message: str, context: list[AgentMessage] | None = None) -> Generator[AgentResponse, None, None]:
        self._should_stop = False

        try:
            self._ensure_server()
        except Exception as e:
            self.logger.error(f"Failed to start server: {e}, {traceback.format_exc()}")
            yield AgentResponse(text="Local LLM server failed to start.", state=AdapterState.ERROR)
            return

        # Build messages for OpenAI-compatible API
        # Context already includes the current user message (appended by the shell)
        messages = [{"role": "system", "content": self._system_prompt}]
        if context:
            for msg in context:
                if msg.role in ("user", "assistant"):
                    messages.append({"role": msg.role, "content": msg.text})
        else:
            messages.append({"role": "user", "content": message})

        yield AgentResponse(text="", state=AdapterState.THINKING)

        try:
            response = requests.post(
                f"http://{self._server.host}:{self._server.port}/v1/chat/completions",
                json={"messages": messages, "stream": True},
                stream=True,
                timeout=60,
            )
            response.raise_for_status()

            full_text = ""
            in_think = False

            for line in response.iter_lines(decode_unicode=True):
                if self._should_stop:
                    yield AgentResponse(text="", state=AdapterState.DONE)
                    return

                if not line or not line.startswith("data: "):
                    continue

                data = line[6:]
                if data.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")

                    if not content:
                        continue

                    # Handle <think> tags (Qwen3 thinking)
                    if "<think>" in content:
                        in_think = True
                        content = content.split("<think>")[0]
                    if "</think>" in content:
                        in_think = False
                        content = content.split("</think>")[-1]
                        continue

                    if in_think:
                        continue

                    if content:
                        full_text += content
                        yield AgentResponse(text=content, state=AdapterState.SPEAKING)

                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

            yield AgentResponse(text="", state=AdapterState.DONE)

        except Exception as e:
            self.logger.error(f"Error during inference: {e}, {traceback.format_exc()}")
            yield AgentResponse(text="I had trouble generating a response.", state=AdapterState.ERROR)

    def is_available(self) -> bool:
        if self._server and self._server.is_running():
            try:
                return self._server.is_up_and_running()
            except Exception:
                return False
        return False

    def stop(self) -> None:
        self._should_stop = True

    def cleanup(self) -> None:
        if self._server:
            self._server.stop()
            self._server = None
        self.logger.info("Local LLM adapter cleaned up.")

    @property
    def name(self) -> str:
        return "local_llm"

    @property
    def description(self) -> str:
        return f"Local llama.cpp server running {self._model_name}"
