import logging
import traceback

from adapter.base import AgentAdapter
from utils.app_logger import AppLogger


class AdapterRegistry:
    """
    Registry for agent adapters. Discover, register, and switch backends at runtime.

    Usage:
        registry = AdapterRegistry()
        registry.register(LocalLLMAdapter(...))
        registry.register(ClaudeAdapter(...))
        registry.set_active("local_llm")
        adapter = registry.active
    """

    def __init__(self):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self._adapters: dict[str, AgentAdapter] = {}
        self._active_name: str | None = None

    def register(self, adapter: AgentAdapter) -> None:
        self._adapters[adapter.name] = adapter
        self.logger.info(f"Registered adapter: {adapter.name}")
        # Auto-select first registered adapter
        if self._active_name is None:
            self._active_name = adapter.name

    def unregister(self, name: str) -> None:
        if name in self._adapters:
            if self._active_name == name:
                self._active_name = None
            adapter = self._adapters.pop(name)
            adapter.cleanup()
            self.logger.info(f"Unregistered adapter: {name}")

    def set_active(self, name: str) -> bool:
        if name not in self._adapters:
            self.logger.warning(f"Adapter '{name}' not found. Available: {list(self._adapters.keys())}")
            return False
        self._active_name = name
        self.logger.info(f"Active adapter: {name}")
        return True

    @property
    def active(self) -> AgentAdapter | None:
        if self._active_name and self._active_name in self._adapters:
            return self._adapters[self._active_name]
        return None

    @property
    def active_name(self) -> str | None:
        return self._active_name

    def list_adapters(self) -> list[dict]:
        """List all registered adapters with availability status."""
        result = []
        for name, adapter in self._adapters.items():
            try:
                available = adapter.is_available()
            except Exception:
                available = False
            result.append({
                "name": name,
                "description": adapter.description,
                "available": available,
                "active": name == self._active_name,
            })
        return result

    def get(self, name: str) -> AgentAdapter | None:
        return self._adapters.get(name)

    def cleanup_all(self) -> None:
        # Snapshot + clear to avoid concurrent iteration issues and double-cleanup
        adapters = list(self._adapters.items())
        self._adapters.clear()
        self._active_name = None
        for name, adapter in adapters:
            try:
                adapter.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up adapter '{name}': {e}, {traceback.format_exc()}")
