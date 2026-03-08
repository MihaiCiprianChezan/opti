"""
ClaudeCLIAdapter — wraps Claude Code CLI via the official claude-agent-sdk.

Uses the SDK's query() for streaming, with token-level deltas via include_partial_messages.
Bridges async SDK → sync Generator[AgentResponse] using a queue + background thread.
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

# Sentinel to signal the async producer is done
_DONE = object()
_ERROR = object()


class ClaudeCLIAdapter(AgentAdapter):
    """
    Adapter for Claude Code CLI via claude-agent-sdk.

    Requires 'claude' on PATH and 'claude-agent-sdk' installed.
    Streams token-level deltas for responsive TTS, with tool-call progress reporting.
    """

    def __init__(self, summarizer: Callable[[str], str] | None = None,
                 cwd: str | None = None, model: str | None = None):
        self._summarizer = summarizer
        self._cwd = cwd
        self._model = model
        self._should_stop = False
        self._digester = OutputDigester(summarizer=summarizer)
        self._logger = AppLogger(name="ClaudeCLIAdapter", log_level=logging.DEBUG)

    def send(self, message: str, context: list[AgentMessage] | None = None) -> Generator[AgentResponse, None, None]:
        self._should_stop = False
        self._digester.reset()
        yield AgentResponse(text="", state=AdapterState.THINKING)

        try:
            from claude_agent_sdk import query, ClaudeAgentOptions
            from claude_agent_sdk.types import (
                AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
            )
        except ImportError:
            yield AgentResponse(text="claude-agent-sdk is not installed.", state=AdapterState.ERROR)
            return

        options = ClaudeAgentOptions(
            model=self._model,
            cwd=self._cwd,
            cli_path=self._resolve_cli_path(),
            include_partial_messages=True,
            permission_mode="bypassPermissions",
            max_turns=25,
        )

        # Queue bridges async SDK → sync generator
        q: queue.Queue = queue.Queue()

        async def _run_query():
            try:
                async for msg in query(prompt=message, options=options):
                    if self._should_stop:
                        break
                    q.put(msg)
                q.put(_DONE)
            except Exception as e:
                self._logger.error(f"Claude SDK query error: {e}, {traceback.format_exc()}")
                q.put((_ERROR, str(e)))

        def _thread_target():
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run_query())
            finally:
                # Shut down async generators and pending transports cleanly
                # to avoid "Event loop is closed" warnings on Windows
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
                loop.close()

        thread = threading.Thread(target=_thread_target, daemon=True, name="ClaudeCLI-Query")
        thread.start()

        # Consume from queue, yield AgentResponse objects
        full_response = ""
        try:
            while True:
                if self._should_stop:
                    break
                try:
                    item = q.get(timeout=0.5)
                except queue.Empty:
                    continue

                if item is _DONE:
                    break
                if isinstance(item, tuple) and item[0] is _ERROR:
                    yield AgentResponse(text=f"Claude CLI error: {item[1]}", state=AdapterState.ERROR)
                    return

                # Process SDK message types
                if isinstance(item, AssistantMessage):
                    for block in item.content:
                        if isinstance(block, TextBlock):
                            full_response += block.text
                            yield AgentResponse(text=block.text, state=AdapterState.SPEAKING)
                        elif isinstance(block, ToolUseBlock):
                            # Report tool usage as progress
                            progress = self._digester.feed_line(f"Using tool: {block.name}")
                            if progress:
                                yield AgentResponse(text=progress, state=AdapterState.TOOL_CALLING)

                elif isinstance(item, ResultMessage):
                    # Final result — if we haven't streamed text yet, use the result text
                    if not full_response and hasattr(item, 'text') and item.text:
                        yield AgentResponse(text=item.text, state=AdapterState.SPEAKING)

        except Exception as e:
            self._logger.error(f"Error processing Claude SDK stream: {e}, {traceback.format_exc()}")
            yield AgentResponse(text=f"Stream error: {e}", state=AdapterState.ERROR)

        yield AgentResponse(text="", state=AdapterState.DONE)

    def stop(self) -> None:
        self._should_stop = True

    def is_available(self) -> bool:
        if not self._resolve_cli_path():
            return False
        try:
            import claude_agent_sdk  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _resolve_cli_path() -> str | None:
        """Resolve the claude CLI path, preferring .cmd on Windows."""
        if os.name == 'nt':
            base = shutil.which("claude")
            if base:
                cmd_path = Path(base).with_suffix('.cmd')
                if cmd_path.exists():
                    return str(cmd_path)
        return shutil.which("claude")

    def cleanup(self) -> None:
        self.stop()

    @property
    def name(self) -> str:
        return "claude_cli"

    @property
    def description(self) -> str:
        return "Claude Code CLI agent (via SDK)"
