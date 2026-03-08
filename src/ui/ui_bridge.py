"""
UIBridge — connects the shell's event bus to the Energy Star widget via Qt signals.
Replaces the old UIService with a thinner, focused bridge.
"""
import logging

from PySide6.QtCore import QObject, Signal

from energy.colors import Colors
from utils.app_logger import AppLogger


class UIBridge(QObject):
    """
    Bridges the event bus (thread-safe) to the Energy Star widget (Qt main thread).

    Emits Qt signals so the Energy Star can safely update from any thread.
    """
    signal_ball = Signal(str, dict)

    def __init__(self, event_bus):
        super().__init__()
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.event_bus = event_bus

        # Subscribe to shell events
        self.event_bus.subscribe("color_change", self._on_color_change)
        self.event_bus.subscribe("ui_command", self._on_ui_command)

    def _on_color_change(self, data: dict) -> None:
        """Translate color_change events to Energy Star commands."""
        color = data.get("color")
        if color:
            self.signal_ball.emit("change_color", {"color": color})
        else:
            # Treat as reset if no color
            self.signal_ball.emit("reset_colorized", {})

    def _on_ui_command(self, data: dict) -> None:
        """Forward arbitrary UI commands to the Energy Star."""
        command = data.get("command", "")
        params = data.get("params", {})
        if command:
            self.signal_ball.emit(command, params)

    def reset(self) -> None:
        """Reset the Energy Star to initial state."""
        self.signal_ball.emit("reset_colorized", {})

    def exit(self) -> None:
        """Signal the Energy Star to close."""
        self.signal_ball.emit("exit", {})
