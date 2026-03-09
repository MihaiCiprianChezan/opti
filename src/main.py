"""
AgentOPTI v2 — Voice + Visual Shell for AI Agents.

This module is the desktop application entry point. It builds the Qt app,
creates the floating Energy Star widget, wires the synchronous event bus to the
UI bridge, initializes voice input and output, registers every available agent
adapter, and starts the shell loop in a background thread.

The runtime is intentionally split across two responsibilities:
  - the Qt main thread owns the Energy Star widget and event loop
  - the shell thread owns voice startup, the agent shell, and adapter activity

That separation keeps the UI responsive while still allowing continuous speech
recognition, streamed agent responses, and clean shutdown through Qt signals.
"""
import os
import sys
import threading
import logging

from PySide6.QtWidgets import QApplication

from adapter.registry import AdapterRegistry
from core.config import Config
from core.event_bus import SynchronousEventBus
from core.shell import AgentShell
from energy.colors import Colors
from energy.star import Star
from ui.ui_bridge import UIBridge
from voice.voice_io import VoiceIO
from utils.app_logger import AppLogger


def register_adapters(registry: AdapterRegistry, config: Config) -> None:
    """Register every adapter that is enabled and currently available.

    Adapters are added conservatively. Missing SDKs, missing CLI binaries, or
    absent API keys do not stop startup. Instead, the unavailable adapter is
    skipped and the rest of the application can continue running.

    The active adapter is selected from config only if it was successfully
    registered.
    """
    logger = AppLogger(name="AdapterSetup", log_level=logging.DEBUG)

    # Local LLM (always available if models exist)
    try:
        from adapter.local_llm import LocalLLMAdapter
        adapter = LocalLLMAdapter(
            model_name=config.inference.model_name,
            host=config.inference.host,
            port=config.inference.port,
        )
        registry.register(adapter)
    except Exception as e:
        logger.warning(f"Local LLM adapter not available: {e}")

    # Claude (needs anthropic package + API key)
    try:
        from adapter.claude import ClaudeAdapter
        api_key = config.cloud.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            registry.register(ClaudeAdapter(api_key=api_key, model=config.cloud.default_claude_model))
        else:
            logger.info("Claude adapter skipped: no ANTHROPIC_API_KEY")
    except ImportError:
        logger.info("Claude adapter skipped: anthropic package not installed")
    except Exception as e:
        logger.warning(f"Claude adapter not available: {e}")

    # OpenAI (needs openai package + API key)
    try:
        from adapter.openai_adapter import OpenAIAdapter
        api_key = config.cloud.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            registry.register(OpenAIAdapter(api_key=api_key, model=config.cloud.default_openai_model))
        else:
            logger.info("OpenAI adapter skipped: no OPENAI_API_KEY")
    except ImportError:
        logger.info("OpenAI adapter skipped: openai package not installed")
    except Exception as e:
        logger.warning(f"OpenAI adapter not available: {e}")

    # --- CLI Agent Adapters (via official SDKs) ---
    cli_cwd = config.cli.cli_cwd or None

    # Claude CLI (via claude-agent-sdk)
    if config.cli.claude_cli_enabled:
        try:
            from adapter.claude_cli import ClaudeCLIAdapter
            adapter = ClaudeCLIAdapter(cwd=cli_cwd)
            if adapter.is_available():
                registry.register(adapter)
            else:
                logger.info("Claude CLI adapter skipped: 'claude' or claude-agent-sdk not available")
        except Exception as e:
            logger.warning(f"Claude CLI adapter not available: {e}")

    # GitHub Copilot CLI (via github-copilot-sdk)
    if config.cli.copilot_cli_enabled:
        try:
            from adapter.copilot_cli import CopilotCLIAdapter
            adapter = CopilotCLIAdapter(cwd=cli_cwd)
            if adapter.is_available():
                registry.register(adapter)
            else:
                logger.info("Copilot CLI adapter skipped: CLI binary or SDK not available")
        except Exception as e:
            logger.warning(f"Copilot CLI adapter not available: {e}")

    # Auggie CLI (via auggie-sdk)
    if config.cli.auggie_cli_enabled:
        try:
            from adapter.auggie_cli import AuggieCLIAdapter
            adapter = AuggieCLIAdapter(cwd=cli_cwd)
            if adapter.is_available():
                registry.register(adapter)
            else:
                logger.info("Auggie CLI adapter skipped: 'auggie' or auggie-sdk not available")
        except Exception as e:
            logger.warning(f"Auggie CLI adapter not available: {e}")

    # Set active adapter from config
    if config.active_adapter and registry.get(config.active_adapter):
        registry.set_active(config.active_adapter)

    logger.info(f"Registered adapters: {[a['name'] for a in registry.list_adapters()]}")
    logger.info(f"Active adapter: {registry.active_name}")


def show_energy_star(qt_app: QApplication, energy_star: Star) -> None:
    """Position and show the Energy Star widget near the lower-right corner.

    The placement uses the primary screen geometry and the widget's current size
    so the star appears in its default desktop position before the Qt event loop
    takes over.
    """
    screen = qt_app.primaryScreen().geometry()
    widget_size = energy_star.size()
    x = screen.width() - widget_size.width() // 1.25
    y = screen.height() - widget_size.height() // 1.20
    energy_star.move(int(x), int(y))
    energy_star.show()


def main(use_hardware_acceleration: bool = True):
    """
    Main entry point for AgentOPTI v2.

    Startup flow:
        1. Load configuration and create the Qt application.
        2. Create the Energy Star widget and event bus.
        3. Bridge shell events into Qt-safe UI signals.
        4. Register all available adapters.
        5. Initialize VoiceIO and AgentShell.
        6. Start the shell loop in a background thread.
        7. Show the UI and enter the Qt event loop.

    Architecture:
        Qt main thread  →  Energy Star UI and widget lifetime
        Shell thread    →  VoiceIO, AgentShell, adapter interaction

    Args:
        use_hardware_acceleration: When True, the Energy Star prefers the GPU
            media path. When False, it falls back to software rendering.
    """
    logger = AppLogger(name="AgentOPTI-v2", log_level=logging.DEBUG)
    logging.getLogger("comtypes").setLevel(logging.WARNING)

    # Configuration
    config = Config()

    # Qt application + Energy Star
    qt_app = QApplication(sys.argv)
    energy_star = Star(use_hardware_acceleration=use_hardware_acceleration)

    # Core event bus
    event_bus = SynchronousEventBus()
    event_bus.logger = logger

    # UI Bridge (connects event bus → Energy Star via Qt signals)
    ui_bridge = UIBridge(event_bus)
    ui_bridge.signal_ball.connect(energy_star.receive_command)

    # Adapter registry
    registry = AdapterRegistry()
    register_adapters(registry, config)

    # Voice I/O
    voice_io = VoiceIO(event_bus, config.voice)

    # Agent Shell (the orchestrator)
    shell = AgentShell(event_bus, registry, config)

    def start_shell():
        """Initialize voice services and keep the shell side alive.

        This function runs inside the dedicated shell thread so the Qt main
        thread stays free for rendering and user interaction. After startup it
        publishes a greeting, then idles in a small loop until voice processing
        stops.
        """
        try:
            logger.info("Initializing VoiceIO...")
            voice_io.initialize()
            voice_io.start()

            # Startup greeting
            event_bus.publish_event("agent_response", {
                "text": "Hello! I'm ready.",
                "speaking_color": Colors.hello,
                "after_color": Colors.initial,
            })

            logger.info("AgentOPTI v2 is running.")

            # Keep thread alive
            while voice_io.running:
                import time
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Shell error: {e}")
        # Cleanup is handled by aboutToQuit — no duplicate cleanup here

    # Start shell in background thread — Qt gets the main thread
    shell_thread = threading.Thread(target=start_shell, daemon=True, name="ShellThread")
    shell_thread.start()

    # Stop background threads BEFORE Qt destroys widgets
    def on_about_to_quit():
        """Stop background services before Qt destroys UI objects."""
        logger.info("Qt shutting down — stopping background services first...")
        voice_io.stop()
        shell.cleanup()
        logger.info("Background services stopped.")

    qt_app.aboutToQuit.connect(on_about_to_quit)

    # Show UI and run Qt event loop
    show_energy_star(qt_app, energy_star)
    logger.info("Energy Star has FREEDOM in the main thread.")

    exit_code = qt_app.exec()
    logger.info("AgentOPTI v2 shut down.")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
