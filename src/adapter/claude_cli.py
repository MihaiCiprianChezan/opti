"""
ClaudeCLIAdapter — wraps Claude Code CLI via the official claude-agent-sdk.

Uses ClaudeSDKClient with a persistent event loop so the Claude process and MCP
servers start ONCE and stay warm, eliminating cold-start latency on every query.
Bridges async SDK → sync Generator[AgentResponse] via queue + run_coroutine_threadsafe.
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

_NPM_BIN = Path(os.environ.get("APPDATA", "")) / "npm"

_MCP_SERVERS = {
    "desktop-commander": {
        "type": "stdio",
        "command": str(_NPM_BIN / "desktop-commander.cmd")
        if (_NPM_BIN / "desktop-commander.cmd").exists()
        else "npx",
        "args": []
        if (_NPM_BIN / "desktop-commander.cmd").exists()
        else ["-y", "@wonderwhy-er/desktop-commander"],
    },
    "filesystem": {
        "type": "stdio",
        "command": str(_NPM_BIN / "mcp-server-filesystem.cmd")
        if (_NPM_BIN / "mcp-server-filesystem.cmd").exists()
        else "npx",
        "args": ["C:/Users/mikac", "C:/development"]
        if (_NPM_BIN / "mcp-server-filesystem.cmd").exists()
        else ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/mikac", "C:/development"],
    },
    "fetch": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-fetch"],
    },
}

_SYSTEM_PROMPT = (
    "You are Opti, a voice-controlled AI assistant running on a Windows desktop. "
    "You have full system access through your MCP tools: "
    "desktop-commander (run shell commands, open apps like notepad/chrome/spotify via 'start <app>'), "
    "filesystem (read/write/copy/move files in C:/Users/mikac and C:/development), "
    "and fetch (retrieve any URL). "
    "Always use your tools to perform tasks directly. "
    "Keep responses short and conversational — the user hears you via text-to-speech. "
    "Use plain sentences only, no markdown, no bullet lists, no code blocks."
)


class ClaudeCLIAdapter(AgentAdapter):
    """
    Adapter for Claude Code CLI via claude-agent-sdk.

    Maintains a persistent ClaudeSDKClient + async event loop so the Claude process
    and MCP servers stay warm between queries — no cold-start per voice command.
    """

    def __init__(self, summarizer: Callable[[str], str] | None = None,
                 cwd: str | None = None, model: str | None = None):
        self._summarizer = summarizer
        self._cwd = cwd
        self._model = model
        self._should_stop = False
        self._digester = OutputDigester(summarizer=summarizer)
        self._logger = AppLogger(name="ClaudeCLIAdapter", log_level=logging.DEBUG)

        # Persistent async infrastructure
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._client = None          # ClaudeSDKClient
        self._connected = False
        self._connect_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Persistent loop + client lifecycle
    # ------------------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Start the persistent event loop thread exactly once."""
        if self._loop and self._loop.is_running():
            return self._loop
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="ClaudeCLI-Loop"
        )
        self._loop_thread.start()
        self._logger.info("Persistent async loop started.")
        return self._loop

    def _ensure_connected(self) -> None:
        """Connect the ClaudeSDKClient once; no-op if already connected."""
        with self._connect_lock:
            if self._connected and self._client:
                return
            loop = self._ensure_loop()
            future = asyncio.run_coroutine_threadsafe(self._connect_async(), loop)
            future.result(timeout=30)

    async def _connect_async(self) -> None:
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        options = self._build_options()
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self._connected = True
        mcp_names = list(_MCP_SERVERS.keys())
        self._logger.info(f"ClaudeSDKClient connected. MCPs: {mcp_names}")

    def _build_options(self):
        from claude_agent_sdk import ClaudeAgentOptions
        return ClaudeAgentOptions(
            model=self._model,
            cwd=self._cwd,
            cli_path=self._resolve_cli_path(),
            include_partial_messages=True,
            permission_mode="bypassPermissions",
            max_turns=25,
            mcp_servers=_MCP_SERVERS,
            system_prompt=_SYSTEM_PROMPT,
        )

    # ------------------------------------------------------------------
    # Send (sync generator, bridges to persistent async client)
    # ------------------------------------------------------------------

    def send(self, message: str, context: list[AgentMessage] | None = None) -> Generator[AgentResponse, None, None]:
        self._should_stop = False
        self._digester.reset()
        yield AgentResponse(text="", state=AdapterState.THINKING)

        try:
            self._ensure_connected()
        except Exception as e:
            self._logger.error(f"Failed to connect ClaudeSDKClient: {e}, {traceback.format_exc()}")
            yield AgentResponse(text="Failed to connect to Claude.", state=AdapterState.ERROR)
            return

        try:
            from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
        except ImportError:
            yield AgentResponse(text="claude-agent-sdk is not installed.", state=AdapterState.ERROR)
            return

        q: queue.Queue = queue.Queue()

        async def _do_query():
            try:
                self._logger.info(f"[query] {message!r:.120}")
                await self._client.query(message)
                async for msg in self._client.receive_response():
                    q.put(msg)
                q.put(_DONE)
            except Exception as e:
                self._logger.error(f"SDK query error: {e}, {traceback.format_exc()}")
                q.put((_ERROR, str(e)))
                # Mark disconnected so next send() reconnects
                self._connected = False
                self._client = None

        asyncio.run_coroutine_threadsafe(_do_query(), self._loop)

        full_response = ""
        tool_call_count = 0
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
                    yield AgentResponse(text=f"Claude error: {item[1]}", state=AdapterState.ERROR)
                    return

                if isinstance(item, AssistantMessage):
                    for block in item.content:
                        if isinstance(block, TextBlock):
                            if block.text:
                                self._logger.debug(f"[text] {block.text[:120]!r}")
                            full_response += block.text
                            yield AgentResponse(text=block.text, state=AdapterState.SPEAKING)
                        elif isinstance(block, ToolUseBlock):
                            tool_call_count += 1
                            self._logger.info(f"[tool] {block.name} | input: {str(block.input)[:200]}")
                            progress = self._digester.feed_line(f"Using tool: {block.name}")
                            if progress:
                                yield AgentResponse(text=progress, state=AdapterState.TOOL_CALLING)

                elif isinstance(item, ResultMessage):
                    cost = f"${item.total_cost_usd:.4f}" if item.total_cost_usd else "n/a"
                    self._logger.info(
                        f"[done] turns={item.num_turns} | tools={tool_call_count} | "
                        f"time={item.duration_ms}ms | cost={cost} | error={item.is_error}"
                    )
                    if not full_response and item.result:
                        yield AgentResponse(text=item.result, state=AdapterState.SPEAKING)

        except Exception as e:
            self._logger.error(f"Error consuming stream: {e}, {traceback.format_exc()}")
            yield AgentResponse(text=f"Stream error: {e}", state=AdapterState.ERROR)

        yield AgentResponse(text="", state=AdapterState.DONE)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self._should_stop = True
        if self._client and self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._safe_interrupt(), self._loop)

    async def _safe_interrupt(self) -> None:
        try:
            await self._client.interrupt()
        except Exception as e:
            self._logger.debug(f"Interrupt error (likely benign): {e}")

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
        self._should_stop = True
        if self._client and self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._connected = False
        self._client = None
        self._logger.info("ClaudeCLIAdapter cleaned up.")

    @property
    def name(self) -> str:
        return "claude_cli"

    @property
    def description(self) -> str:
        return "Claude Code CLI agent (via SDK)"
