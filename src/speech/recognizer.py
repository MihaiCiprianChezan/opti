"""
SpeechRecognizer — faster-whisper based ASR with VAD silence detection.

Records audio chunks, detects speech/silence via RMS energy, then transcribes
the accumulated utterance with faster-whisper on CUDA (falls back to CPU).
Whisper outputs punctuated text natively — no post-processing needed.
"""
import logging
import traceback

import numpy as np
import pyaudio
from faster_whisper import WhisperModel

from utils.app_logger import AppLogger

SAMPLE_RATE = 16000
CHUNK_FRAMES = 1024
SPEECH_START_THRESHOLD = 600  # RMS above this starts recording (keeps false triggers low)
SPEECH_END_THRESHOLD = 300    # RMS below this counts as silence (hysteresis — easier to stop)
MIN_SPEECH_CHUNKS = 8         # ~0.5s of speech required before transcribing
SILENCE_CHUNKS_REQUIRED = 12  # ~0.8s of silence to end an utterance
MAX_UTTERANCE_SECONDS = 30    # safety cap on recording length


class SpeechRecognizer:
    """Real-time speech recognizer using faster-whisper with silence-based VAD."""

    def __init__(self, model_size: str = "base.en", device: str = "cuda", compute_type: str = "float16"):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self._stream = None
        self._audio_interface = None
        self._is_running = False
        self.model = self._load_model(model_size, device, compute_type)

    def _load_model(self, model_size: str, device: str, compute_type: str) -> WhisperModel:
        """Load faster-whisper model, fall back to CPU/int8 if CUDA unavailable."""
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            self.logger.info(f"Faster-Whisper '{model_size}' loaded on {device} ({compute_type})")
            return model
        except Exception as e:
            self.logger.warning(f"CUDA load failed ({e}), falling back to CPU int8")
            try:
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
                self.logger.info(f"Faster-Whisper '{model_size}' loaded on CPU (int8)")
                return model
            except Exception as e2:
                self.logger.critical(f"Failed to load Faster-Whisper model: {e2}, {traceback.format_exc()}")
                return None

    def _start_stream(self):
        """Open pyaudio input stream if not already open."""
        if self._stream and self._stream.is_active():
            return
        self._audio_interface = pyaudio.PyAudio()
        self._stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_FRAMES,
        )
        self._stream.start_stream()
        self._is_running = True
        self.logger.debug("ASRx[/] Audio stream started successfully.")

    def recognize(self) -> str:
        """
        Block until a complete utterance is detected, then return transcribed text.
        Uses RMS energy to detect speech onset and silence to detect end-of-utterance.
        Returns empty string if no speech captured.
        """
        if not self.model:
            return ""

        try:
            self._start_stream()
        except Exception as e:
            self.logger.error(f"ASRx[/] Error starting audio stream: {e}, {traceback.format_exc()}")
            return ""

        audio_buffer = []
        speech_chunks = 0
        silence_chunks = 0
        in_speech = False
        max_chunks = int(MAX_UTTERANCE_SECONDS * SAMPLE_RATE / CHUNK_FRAMES)

        try:
            while len(audio_buffer) < max_chunks:
                data = self._stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                chunk = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))

                if rms > SPEECH_START_THRESHOLD:
                    in_speech = True
                    silence_chunks = 0
                    speech_chunks += 1
                    audio_buffer.append(chunk)
                elif in_speech:
                    audio_buffer.append(chunk)  # always record post-onset audio
                    if rms < SPEECH_END_THRESHOLD:
                        silence_chunks += 1
                        if silence_chunks >= SILENCE_CHUNKS_REQUIRED:
                            break  # utterance complete
                    # middle zone (END_THRESHOLD..START_THRESHOLD): buffer it, don't affect silence count

            if speech_chunks < MIN_SPEECH_CHUNKS:
                return ""

            # Normalize to float32 [-1, 1] for Whisper
            audio_np = np.concatenate(audio_buffer).astype(np.float32) / 32768.0

            segments, _ = self.model.transcribe(
                audio_np,
                language="en",
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text for seg in segments).strip()
            return text

        except Exception as e:
            self.logger.error(f"ASRx[/] Error during recognition: {e}, {traceback.format_exc()}")
            if "Invalid handle" in str(e):
                self.cleanup()
            return ""

    def cleanup(self):
        """Release audio resources."""
        self._is_running = False
        if self._stream:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                self.logger.error(f"ASRx[/] Error closing stream: {e}")
            self._stream = None
        if self._audio_interface:
            try:
                self._audio_interface.terminate()
            except Exception as e:
                self.logger.error(f"ASRx[/] Error terminating audio interface: {e}")
            self._audio_interface = None

    @property
    def is_running(self) -> bool:
        return self._is_running and self._stream is not None and self._stream.is_active()


if __name__ == "__main__":
    recognizer = SpeechRecognizer()
    try:
        print("Faster-Whisper ASR started. Speak into the microphone...")
        while True:
            text = recognizer.recognize()
            if text:
                print(f"Recognized: {text}")
    except KeyboardInterrupt:
        print("\nStopped.")
        recognizer.cleanup()
