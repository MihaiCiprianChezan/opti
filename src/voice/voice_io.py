"""
VoiceIO — unified voice input/output service for AgentOPTI v2.

Wraps the existing ASRx (speech recognition) and uses pyttsx3 + pygame for TTS,
publishing events to the shell's event bus.

TTS uses a dedicated worker thread with engine-per-utterance to avoid the known
pyttsx3 runAndWait() hang bug on Windows SAPI5. Playback via pygame is
interruptible — the user can stop the agent mid-sentence.
"""
import logging
import os
import tempfile
import threading
import traceback
from queue import Queue, Empty

import pygame

from core.event_bus import SynchronousEventBus
from core.config import VoiceConfig
from energy.colors import Colors
from speech.asr import ASRx
from utils.app_logger import AppLogger


class VoiceIO:
    """
    Combined voice input/output service.

    - Starts ASR in a background thread, publishes 'user_speech' events
    - Listens for 'agent_response' events and speaks them via TTS
    - Handles speech interruption (stops playback when user starts talking)

    TTS pipeline: pyttsx3 save_to_file (engine-per-utterance) → pygame playback.
    Both steps run in a single dedicated worker thread to keep things simple.
    """

    def __init__(self, event_bus: SynchronousEventBus, config: VoiceConfig = None):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.event_bus = event_bus
        self.config = config or VoiceConfig()
        self.running = False

        # ASR
        self._asr_queue = Queue(100)
        self._asr: ASRx | None = None
        self._asr_poll_thread: threading.Thread | None = None

        # TTS — dedicated worker thread + queue
        self._tts_queue: Queue = Queue()
        self._tts_thread: threading.Thread | None = None
        self._tts_ready = threading.Event()
        self._speaking = False
        self._stop_tts = threading.Event()  # Cross-thread interrupt signal

        # Subscribe to events
        self.event_bus.subscribe("agent_response", self._handle_agent_response)
        self.event_bus.subscribe("interrupt_speech", self._handle_interrupt)
        self.event_bus.subscribe("clear_queues", self._handle_clear)

    def initialize(self) -> None:
        """Initialize ASR and start TTS worker thread."""
        self.logger.info("Initializing VoiceIO...")
        self.running = True

        # Initialize pygame mixer once
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        # Start TTS worker thread
        self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True, name="VoiceIO-TTS")
        self._tts_thread.start()

        # Wait for TTS init to complete
        self._tts_ready.wait(timeout=10)

        # Initialize ASR
        if self.config.asr_enabled:
            self._asr = ASRx(queue=self._asr_queue)
            self._asr.initialize_sync()
            self.logger.info("ASR initialized.")

    def _tts_worker(self) -> None:
        """
        Dedicated TTS worker — generates audio with a fresh pyttsx3 engine per
        utterance, then plays it via pygame (interruptible).
        """
        import pyttsx3

        # Validate that we can create an engine and cache voice map
        try:
            engine = pyttsx3.init("sapi5", debug=False)
            voices = engine.getProperty("voices")
            voice_map = {v.name: v.id for v in voices}
            engine.stop()
            del engine
            self.logger.info(f"TTS worker ready. {len(voice_map)} voices available.")
        except Exception as e:
            self.logger.error(f"TTS init failed: {e}, {traceback.format_exc()}")
            self._tts_ready.set()
            return

        self._tts_ready.set()

        # Process TTS requests from queue
        while self.running:
            try:
                item = self._tts_queue.get(timeout=0.1)
            except Empty:
                continue

            if item is None:  # Shutdown sentinel
                break

            text, speaking_color, after_color, is_stream, done_event = item

            try:
                self._speaking = True
                self._stop_tts.clear()
                self.logger.info(f"TTS speaking: '{text}'")

                # --- Step 1: Generate audio file with fresh engine ---
                audio_file = tempfile.mktemp(suffix=".wav")
                engine = pyttsx3.init("sapi5", debug=False)
                voice_id = voice_map.get(self.config.tts_voice)
                if voice_id:
                    engine.setProperty("voice", voice_id)
                engine.setProperty("rate", self.config.tts_rate)
                engine.save_to_file(text, audio_file)
                engine.runAndWait()
                engine.stop()
                del engine

                # Check if interrupted during generation
                if self._stop_tts.is_set():
                    self._cleanup_file(audio_file)
                    self.logger.info(f"TTS interrupted during generation: '{text[:40]}'")
                    continue

                # --- Step 2: Play via pygame (interruptible) ---
                self.event_bus.publish_event("color_change", speaking_color)

                try:
                    if not pygame.mixer.get_init():
                        pygame.mixer.init()
                    sound = pygame.mixer.Sound(audio_file)
                    sound.play()

                    # Wait for playback, checking stop flag
                    while pygame.mixer.get_busy():
                        if self._stop_tts.is_set():
                            sound.stop()
                            self.logger.info(f"TTS interrupted during playback: '{text[:40]}'")
                            break
                        self._stop_tts.wait(timeout=0.05)
                finally:
                    self._cleanup_file(audio_file)

                # Signal color change after speaking (only if not interrupted and not streaming)
                if not self._stop_tts.is_set() and not is_stream:
                    self.event_bus.publish_event("color_change", after_color)

                self.logger.info(f"TTS finished: '{text[:50]}'")

            except Exception as e:
                self.logger.error(f"TTS error: {e}, {traceback.format_exc()}")
            finally:
                self._speaking = False
                if done_event:
                    done_event.set()

        self.logger.info("TTS worker stopped.")

    @staticmethod
    def _cleanup_file(path: str) -> None:
        """Remove temp audio file if it exists."""
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass

    def start(self) -> None:
        """Start listening for speech."""
        if self._asr and self.config.asr_enabled:
            self._asr.start()
            self._asr_poll_thread = threading.Thread(
                target=self._poll_asr, daemon=True, name="VoiceIO-ASR-Poll"
            )
            self._asr_poll_thread.start()
            self.logger.info("ASR listening started.")

    def _poll_asr(self) -> None:
        """Poll ASR queue and publish recognized speech to event bus."""
        while self.running:
            try:
                text = self._asr_queue.get(timeout=0.1)
                if text and text.strip():
                    self.logger.debug(f"Speech recognized: '{text}'")
                    # Filter STT noise: single words under 5 chars don't interrupt or get published
                    words = text.strip().split()
                    if len(words) == 1 and len(words[0]) < 5:
                        self.logger.debug(f"Ignoring short STT noise: '{text}'")
                        continue
                    # Interrupt current speech when user talks
                    if self._speaking:
                        self.interrupt()
                    # Publish to shell
                    self.event_bus.publish_event("user_speech", {"text": text})
            except Exception:
                pass

    def interrupt(self) -> None:
        """Stop current TTS playback and drain pending queue."""
        self._stop_tts.set()
        # Drain pending TTS items and signal their done events
        while not self._tts_queue.empty():
            try:
                item = self._tts_queue.get_nowait()
                if item is not None:
                    _, _, _, _, done_event = item
                    if done_event:
                        done_event.set()  # Unblock any waiting publisher
            except Empty:
                break
        self.event_bus.publish_event("color_change", Colors.initial)

    def _handle_agent_response(self, data: dict) -> None:
        """Queue agent response for TTS playback. Blocks until spoken."""
        text = data.get("text", "").strip()
        if not text:
            return

        speaking_color = data.get("speaking_color", Colors.speaking)
        after_color = data.get("after_color", Colors.initial)
        is_stream = data.get("stream", False)

        # Use a done event so the caller blocks until TTS finishes this sentence
        done_event = threading.Event()
        self._tts_queue.put((text, speaking_color, after_color, is_stream, done_event))
        done_event.wait(timeout=30)  # 30s max per sentence

    def _handle_interrupt(self, data=None) -> None:
        """Handle interrupt event from event bus."""
        self.interrupt()

    def _handle_clear(self, data=None) -> None:
        """Clear ASR and TTS queues."""
        self.interrupt()
        while not self._asr_queue.empty():
            try:
                self._asr_queue.get_nowait()
            except Empty:
                break

    def speak(self, text: str, lang: str = None) -> None:
        """Directly speak text (for programmatic use)."""
        if text.strip():
            done_event = threading.Event()
            self._tts_queue.put((text, Colors.speaking, Colors.initial, False, done_event))
            done_event.wait(timeout=30)

    def stop(self) -> None:
        """Stop all voice I/O."""
        self.running = False
        self.interrupt()
        self._tts_queue.put(None)  # Shutdown sentinel
        if self._asr:
            self._asr.stop()
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        self.logger.info("VoiceIO stopped.")

    def cleanup(self) -> None:
        """Release all resources."""
        self.stop()
        self.logger.info("VoiceIO cleaned up.")

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def is_listening(self) -> bool:
        return self._asr.is_active if self._asr else False
