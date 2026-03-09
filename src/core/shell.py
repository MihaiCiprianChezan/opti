"""
AgentShell — the core orchestrator for AgentOPTI v2.

Replaces the old service mesh (DispatcherService, IntentService, ToolService, ChatService)
with a single flow: Voice → Adapter → Voice + UI.
"""
import logging
import re
import threading
import traceback

from adapter.base import AgentMessage, AgentResponse, AdapterState
from adapter.registry import AdapterRegistry
from core.event_bus import SynchronousEventBus
from core.config import Config
from energy.colors import Colors
from utils.app_logger import AppLogger
from utils.text_clean import TextCleaner

# Matches non-speakable characters: mojibake (Ã°ÂÂ), emojis, control chars, etc.
# Keeps ASCII printable (space-tilde) — sufficient for English TTS.
_NON_SPEAKABLE_RE = re.compile(r'[^\x20-\x7E]+')
# Strips XML/HTML tags (e.g. auggie SDK structured output: <augment-agent-result>...)
_XML_TAGS_RE = re.compile(r'<[^>]+>')



# Map adapter states to Energy Star colors
STATE_COLORS = {
    AdapterState.THINKING: Colors.generating,
    AdapterState.SPEAKING: Colors.speaking,
    AdapterState.TOOL_CALLING: Colors.operating_text,
    AdapterState.DONE: Colors.initial,
    AdapterState.ERROR: Colors.profanity,
    AdapterState.IDLE: Colors.initial,
}


class AgentShell:
    """
    Orchestrates the voice-visual-agent loop:
      1. Listens for user speech (via event bus)
      2. Sends it to the active adapter
      3. Streams responses back to TTS + UI
    """

    def __init__(self, event_bus: SynchronousEventBus, registry: AdapterRegistry, config: Config):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.event_bus = event_bus
        self.event_bus.logger = self.logger
        self.registry = registry
        self.config = config
        self.context: list[AgentMessage] = []
        self._processing = False
        self._processing_lock = threading.Lock()
        self._should_stop = threading.Event()

        # Reuse battle-tested text cleaning from old codebase
        self._text_cleaner = TextCleaner()

        # Subscribe to voice events
        self.event_bus.subscribe("user_speech", self._handle_user_speech)
        # Subscribe to adapter switch requests
        self.event_bus.subscribe("switch_adapter", self._handle_switch_adapter)

    def _handle_user_speech(self, data: dict) -> None:
        """Handle recognized speech from VoiceIO."""
        text = data.get("text", "").strip()
        if not text:
            return

        with self._processing_lock:
            if self._processing:
                # Interrupt current processing — user spoke over the agent
                self.logger.info(f"Interrupting current response for new input: '{text}'")
                self._should_stop.set()
                self.stop_current()
                # Don't start new processing here — wait for the current thread to release
                # The interrupt+queue drain in VoiceIO handles the TTS side
                return
            self._processing = True

        # Process in a thread to not block the event bus
        self._should_stop.clear()
        thread = threading.Thread(target=self._process_message, args=(text,), daemon=True, name="ShellProcessing")
        thread.start()

    def _process_message(self, text: str) -> None:
        """Send text to active adapter, collect full response, then speak it."""
        try:
            adapter = self.registry.active
            if not adapter:
                self.logger.error("No active adapter available.")
                self.event_bus.publish_event("agent_response", {
                    "text": "No agent backend is currently available.",
                    "speaking_color": Colors.profanity,
                    "after_color": Colors.initial,
                })
                return

            # Add user message to context
            self.context.append(AgentMessage(text=text, role="user"))

            self.logger.info(f"Processing: '{text}' via {adapter.name}")

            # Signal thinking state
            self.event_bus.publish_event("color_change", STATE_COLORS[AdapterState.THINKING])

            # Collect sentences from the adapter stream
            sentences = []
            current_sentence = ""
            full_response = ""

            for response in adapter.send(text, context=self.context):
                if self._should_stop.is_set():
                    self.logger.info("Processing interrupted by user.")
                    break

                # CLI adapters emit TOOL_CALLING with progress text — speak immediately
                if response.state == AdapterState.TOOL_CALLING and response.text:
                    cleaned = self._text_cleaner.deep_text_clean(response.text)
                    cleaned = _XML_TAGS_RE.sub(' ', cleaned)
                    cleaned = _NON_SPEAKABLE_RE.sub('', cleaned).strip()
                    if cleaned:
                        self.event_bus.publish_event("agent_response", {
                            "text": cleaned,
                            "speaking_color": STATE_COLORS[AdapterState.TOOL_CALLING],
                            "after_color": STATE_COLORS[AdapterState.TOOL_CALLING],
                            "stream": True,
                        })
                elif response.text:
                    current_sentence += response.text
                    full_response += response.text

                    # Split into sentences as they complete
                    if self._is_sentence_end(current_sentence):
                        sentences.append(current_sentence.strip())
                        current_sentence = ""

            # Flush remaining text
            if current_sentence.strip() and not self._should_stop.is_set():
                sentences.append(current_sentence.strip())

            self.logger.info(f"LLM returned {len(sentences)} sentences.")

            # Clean and speak sentences sequentially
            for i, sentence in enumerate(sentences):
                if self._should_stop.is_set():
                    self.logger.info("TTS interrupted, stopping remaining sentences.")
                    break

                # Clean text: markdown → emojis → mojibake → whitespace
                sentence = self._text_cleaner.deep_text_clean(sentence)
                sentence = _XML_TAGS_RE.sub(' ', sentence)
                sentence = _NON_SPEAKABLE_RE.sub('', sentence).strip()
                if not sentence:
                    continue

                is_last = (i == len(sentences) - 1)
                self.event_bus.publish_event("agent_response", {
                    "text": sentence,
                    "speaking_color": Colors.speaking,
                    "after_color": Colors.initial if is_last else Colors.speaking,
                    "stream": not is_last,
                })

            # Add assistant response to context
            if full_response:
                self.context.append(AgentMessage(text=full_response, role="assistant"))

            # Signal done
            if not self._should_stop.is_set():
                self.event_bus.publish_event("color_change", STATE_COLORS[AdapterState.DONE])

        except Exception as e:
            self.logger.error(f"Error processing message: {e}, {traceback.format_exc()}")
            self.event_bus.publish_event("agent_response", {
                "text": "I encountered an error processing your request.",
                "speaking_color": Colors.profanity,
                "after_color": Colors.initial,
            })
        finally:
            self._processing = False

    @staticmethod
    def _is_sentence_end(text: str) -> bool:
        """Check if text ends with a sentence-ending punctuation."""
        stripped = text.rstrip()
        return stripped and stripped[-1] in ".!?;:"

    def _handle_switch_adapter(self, data: dict) -> None:
        """Switch the active adapter at runtime."""
        name = data.get("name", "")
        if self.registry.set_active(name):
            self.logger.info(f"Switched to adapter: {name}")
            self.event_bus.publish_event("agent_response", {
                "text": f"Switched to {name} backend.",
                "speaking_color": Colors.hello,
                "after_color": Colors.initial,
            })
        else:
            self.event_bus.publish_event("agent_response", {
                "text": f"Backend {name} is not available.",
                "speaking_color": Colors.uncertain,
                "after_color": Colors.initial,
            })

    def clear_context(self) -> None:
        """Clear conversation context."""
        self.context.clear()
        self.logger.info("Conversation context cleared.")

    def stop_current(self) -> None:
        """Stop the currently active adapter's processing."""
        adapter = self.registry.active
        if adapter:
            adapter.stop()

    def cleanup(self) -> None:
        """Cleanup shell and all adapters."""
        self.registry.cleanup_all()
        self.event_bus.clear_all()
        self.logger.info("Shell cleaned up.")
