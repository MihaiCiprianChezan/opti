"""
SynchronousEventBus — extracted from utils/threads.py for the v2 architecture.
Kept identical to preserve compatibility with existing UI and voice components.
"""
import traceback
from typing import Dict, List, Callable, Any, Optional

from utils.app_logger import AppLogger


class SynchronousEventBus:
    """A synchronous event bus for pure threaded communication"""

    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.logger: Optional[AppLogger] = None

    def publish_event(self, event_name: str, data: Any = None) -> None:
        if event_name not in self.subscribers:
            return
        if self.logger:
            self.logger.debug(f"[EventBus] Publishing '{event_name}'")
        for callback in self.subscribers[event_name]:
            try:
                callback(data)
            except Exception as e:
                if self.logger:
                    self.logger.error(f"[EventBus] Error in handler for '{event_name}': {e}, {traceback.format_exc()}")

    def subscribe(self, event_name: str, callback: Callable) -> None:
        if event_name not in self.subscribers:
            self.subscribers[event_name] = []
        if callback not in self.subscribers[event_name]:
            self.subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Callable) -> None:
        if event_name in self.subscribers and callback in self.subscribers[event_name]:
            self.subscribers[event_name].remove(callback)

    # Alias for backward compat
    publish_sync = publish_event

    def clear_all(self) -> None:
        self.subscribers.clear()
