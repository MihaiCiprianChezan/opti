"""
CopilotCLIAdapter — wraps GitHub Copilot CLI via the official github-copilot-sdk.

Uses CopilotClient + CopilotSession for async streaming with multi-turn support.
Bridges async SDK → sync Generator[AgentResponse] using a queue + background thread.

Requires:
  - GitHub Copilot CLI installed: npm install -g @github/copilot
  - github-copilot-sdk installed: pip install github-copilot-sdk
  - Active Copilot subscription (Pro, Pro+, Business, or Enterprise)
"""
import asyncio
import logging
import os
import queue
import shutil
import threading
import traceback
from pathlib import Path
from typing import Callable, Generator

from adapter.base import AgentAdapter, AgentMessage, AgentResponse, AdapterState
from adapter.cli_digest import OutputDigester
from utils.app_logger import AppLogger

_DONE = object()
_ERROR = object()


class CopilotCLIAdapter(AgentAdapter):
    """
    Adapter for GitHub Copilot CLI via github-copilot-sdk.

    Requires the Copilot CLI binary on PATH and github-copilot-sdk installed.
    Uses async CopilotSession.send() with event streaming.
    """

    def __init__(self, summarizer: Callable[[str], str] | None = None,
                 cwd: str | None = None, model: str | None = None):
        self._summarizer = summarizer
        self._cwd = cwd
        self._model = model or "gpt-4o"
        self._should_stop = False
        self._digester = OutputDigester(summarizer=summarizer)
        self._logger = AppLogger(name="CopilotCLIAdapter", log_level=logging.DEBUG)

    def send(self, message: str, context: list[AgentMessage] | None = None) -> Generator[AgentResponse, None, None]:
        self._should_stop = False
        self._digester.reset()
        yield AgentResponse(text="", state=AdapterState.THINKING)

        try:
            from copilot import CopilotClient, SessionConfig, PermissionHandler
        except ImportError:
            yield AgentResponse(text="github-copilot-sdk is not installed.", state=AdapterState.ERROR)
            return

        q: queue.Queue = queue.Queue()

        async def _run():
            client = None
            try:
                client = CopilotClient()
                await client.start()

                session = await client.create_session(SessionConfig(
                    model=self._model,
                    on_permission_request=PermissionHandler.approve_all,
                ))

                # Single event handler — Copilot SDK dispatches all events to one callback
                def on_event(event):
                    if self._should_stop:
                        return
                    etype = event.type.value if hasattr(event.type, 'value') else str(event.type)
                    data = event.data

                    # Text streaming events
                    if etype in ("assistant.message_delta", "assistant.streaming_delta"):
                        text = getattr(data, 'text', '') or getattr(data, 'content', '')
                        if not text and isinstance(data, dict):
                            text = data.get('text', '') or data.get('content', '')
                        if text:
                            q.put(("text", text))
                    # Full message (fallback if deltas aren't emitted)
                    elif etype == "assistant.message":
                        text = getattr(data, 'content', '') or getattr(data, 'text', '')
                        if not text and isinstance(data, dict):
                            text = data.get('content', '') or data.get('text', '')
                        if text:
                            q.put(("text", text))
                    # Tool progress
                    elif etype.startswith("tool."):
                        title = getattr(data, 'title', None) or getattr(data, 'name', 'tool')
                        if isinstance(data, dict):
                            title = data.get('title', data.get('name', 'tool'))
                        progress = self._digester.feed_line(f"Using tool: {title}")
                        if progress:
                            q.put(("progress", progress))

                session.on(on_event)

                # Send message and wait for completion
                await session.send_and_wait({"prompt": message})

                await session.disconnect()
                q.put(_DONE)
            except Exception as e:
                self._logger.error(f"Copilot SDK error: {e}, {traceback.format_exc()}")
                q.put((_ERROR, str(e)))
            finally:
                if client:
                    try:
                        await client.stop()
                    except Exception:
                        pass

        def _thread_target():
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
                loop.close()

        thread = threading.Thread(target=_thread_target, daemon=True, name="Copilot-Query")
        thread.start()

        # Consume from queue
        full_response = ""
        try:
            while True:
                if self._should_stop:
                    break
                try:
                    item = q.get(timeout=0.5)
                except queue.Empty:
                    if not thread.is_alive():
                        break
                    continue

                if item is _DONE:
                    break
                if isinstance(item, tuple) and len(item) == 2:
                    kind, text = item
                    if kind is _ERROR:
                        yield AgentResponse(text=f"Copilot error: {text}", state=AdapterState.ERROR)
                        return
                    elif kind == "progress":
                        yield AgentResponse(text=text, state=AdapterState.TOOL_CALLING)
                    elif kind == "text":
                        full_response += text
                        yield AgentResponse(text=text, state=AdapterState.SPEAKING)

        except Exception as e:
            self._logger.error(f"Error processing Copilot stream: {e}, {traceback.format_exc()}")
            yield AgentResponse(text=f"Stream error: {e}", state=AdapterState.ERROR)

        if not full_response:
            yield AgentResponse(text="Copilot completed with no response.", state=AdapterState.SPEAKING)

        yield AgentResponse(text="", state=AdapterState.DONE)

    def stop(self) -> None:
        self._should_stop = True

    def is_available(self) -> bool:
        if not self._resolve_cli_path():
            return False
        try:
            import copilot  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _resolve_cli_path() -> str | None:
        """Resolve the copilot CLI path, preferring .cmd on Windows."""
        for cmd_name in ("copilot", "github-copilot"):
            base = shutil.which(cmd_name)
            if base:
                if os.name == 'nt':
                    cmd_path = Path(base).with_suffix('.cmd')
                    if cmd_path.exists():
                        return str(cmd_path)
                return base
        return None

    def cleanup(self) -> None:
        self.stop()

    @property
    def name(self) -> str:
        return "copilot_cli"

    @property
    def description(self) -> str:
        return "GitHub Copilot CLI agent (via SDK)"
