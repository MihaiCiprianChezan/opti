"""
AuggieCLIAdapter — wraps Augment CLI via the official auggie-sdk.

Uses the Auggie class with AgentListener for streaming callbacks.
The SDK is fully synchronous — no async bridging needed.
Runs Auggie.run() in a sub-thread, listener pushes events to a queue,
send() generator reads from the queue.

TODO: Needs further testing — auggie-sdk returns empty errors on Windows,
      possibly related to workspace indexing or ACP startup. Low priority
      compared to Claude CLI and Copilot adapters.
"""
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


class AuggieCLIAdapter(AgentAdapter):
    """
    Adapter for Augment CLI (auggie) via auggie-sdk.

    Requires 'auggie' on PATH and 'auggie-sdk' installed.
    Uses AgentListener callbacks for tool-call progress and final message.
    """

    def __init__(self, summarizer: Callable[[str], str] | None = None,
                 cwd: str | None = None, model: str | None = None):
        self._summarizer = summarizer
        self._cwd = cwd
        self._model = model
        self._should_stop = False
        self._digester = OutputDigester(summarizer=summarizer)
        self._logger = AppLogger(name="AuggieCLIAdapter", log_level=logging.DEBUG)

    def send(self, message: str, context: list[AgentMessage] | None = None) -> Generator[AgentResponse, None, None]:
        self._should_stop = False
        self._digester.reset()
        yield AgentResponse(text="", state=AdapterState.THINKING)

        try:
            from auggie_sdk import Auggie, AgentListener
        except ImportError:
            yield AgentResponse(text="auggie-sdk is not installed.", state=AdapterState.ERROR)
            return

        # Queue bridges listener callbacks → sync generator
        q: queue.Queue = queue.Queue()

        class _VoiceListener(AgentListener):
            def __init__(self, digester: OutputDigester):
                self._digester = digester

            def on_tool_call(self, tool_call_id: str, title: str,
                             kind: str | None = None, status: str | None = None) -> None:
                progress = self._digester.feed_line(f"Using tool: {title}")
                if progress:
                    q.put(("progress", progress))

            def on_agent_message(self, message: str) -> None:
                q.put(("message", message))

            def on_agent_thought(self, text: str) -> None:
                pass  # skip internal reasoning for TTS

        listener = _VoiceListener(self._digester)

        def _run():
            try:
                agent = Auggie(
                    workspace_root=self._cwd,
                    model=self._model,
                    listener=listener,
                    cli_path=self._resolve_cli_path(),
                )
                agent.run(message)
                q.put(_DONE)
            except Exception as e:
                self._logger.error(f"Auggie SDK error: {e}, {traceback.format_exc()}")
                q.put((_ERROR, str(e)))

        thread = threading.Thread(target=_run, daemon=True, name="Auggie-Run")
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
                    # Check if thread is still alive
                    if not thread.is_alive():
                        break
                    continue

                if item is _DONE:
                    break
                if isinstance(item, tuple) and len(item) == 2:
                    kind, text = item
                    if kind is _ERROR:
                        yield AgentResponse(text=f"Auggie error: {text}", state=AdapterState.ERROR)
                        return
                    elif kind == "progress":
                        yield AgentResponse(text=text, state=AdapterState.TOOL_CALLING)
                    elif kind == "message":
                        full_response += text
                        yield AgentResponse(text=text, state=AdapterState.SPEAKING)

        except Exception as e:
            self._logger.error(f"Error processing Auggie stream: {e}, {traceback.format_exc()}")
            yield AgentResponse(text=f"Stream error: {e}", state=AdapterState.ERROR)

        # If no message was streamed, get summary from the digester
        if not full_response:
            yield AgentResponse(text="Auggie completed with no response.", state=AdapterState.SPEAKING)

        yield AgentResponse(text="", state=AdapterState.DONE)

    def stop(self) -> None:
        self._should_stop = True

    def is_available(self) -> bool:
        if not self._resolve_cli_path():
            return False
        try:
            import auggie_sdk  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _resolve_cli_path() -> str | None:
        """Resolve the auggie CLI path, preferring .cmd on Windows."""
        if os.name == 'nt':
            # On Windows, npm scripts need the .cmd wrapper for subprocess spawning
            base = shutil.which("auggie")
            if base:
                cmd_path = Path(base).with_suffix('.cmd')
                if cmd_path.exists():
                    return str(cmd_path)
        return shutil.which("auggie")

    def cleanup(self) -> None:
        self.stop()

    @property
    def name(self) -> str:
        return "auggie_cli"

    @property
    def description(self) -> str:
        return "Augment CLI (auggie) agent (via SDK)"
