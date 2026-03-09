import json
import logging
import traceback
from typing import Optional, Tuple

import pyaudio
import vosk
from vosk import Model, KaldiRecognizer

from pathlib import Path

# VOSK_MODEL_PATH = str(Path(__file__).parent.parent.parent / "models" / "vosk-model-small-en-us-0.15")
VOSK_MODEL_PATH = str(Path(__file__).parent.parent.parent / "models" / "vosk-model-en-us-0.22-lgraph")

vosk.SetLogLevel(0)
from utils.app_logger import AppLogger


class SpeechRecognizer:
    """Handles speech recognition using Vosk with pure threading support."""

    def __init__(self, model_path=VOSK_MODEL_PATH):
        self.name = self.__class__.__name__
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self._stream = None
        self._audio_interface = None
        self._is_running = False
        self.model, self.recognizer = self.initialize(model_path)

    def initialize(self, model_path) -> Tuple[Optional[Model], Optional[KaldiRecognizer]]:
        """Initialize the Vosk speech recognition model."""
        try:
            model = vosk.Model(model_path)
            recognizer = vosk.KaldiRecognizer(model, 16000)
            self.logger.debug(f"ASRx[/] AI model initialized successfully.")
            return model, recognizer
        except Exception as e:
            self.logger.critical(f"ASRx[/] <ASR will not function without the model> Critical Error initializing AI model {e}, {traceback.format_exc()}")
            return None, None

    def start_audio_stream(self, sample_rate=16000, channels=1, frames_per_buffer=8000, format=pyaudio.paInt16):
        """Initialize and start the audio stream."""
        try:
            if self._stream and self._stream.is_active():
                return

            self._audio_interface = pyaudio.PyAudio()
            self._stream = self._audio_interface.open(
                format=format,
                channels=channels,
                rate=sample_rate,
                input=True,
                frames_per_buffer=frames_per_buffer
            )
            self._stream.start_stream()
            self._is_running = True
            self.logger.debug(f"ASRx[/] Audio stream started successfully.")
        except Exception as e:
            self.logger.error(f"ASRx[/] Error starting audio stream: {e}")
            self.cleanup()
            raise

    def recognize(self, sample_rate=16000, channels=1, frames_per_buffer=8000, num_frames=4000, format=pyaudio.paInt16):
        """Recognize speech using Vosk."""
        if not self.model or not self.recognizer:
            self.logger.warning(f"ASRx[/] AI model is not initialized.")
            return ""

        # Ensure we have an active audio stream
        if not self._stream or not self._stream.is_active():
            try:
                self.start_audio_stream(sample_rate, channels, frames_per_buffer, format)
            except Exception as e:
                self.logger.error(f"ASRx[/] Error initializing audio stream: {e}")
                return ""

        try:
            data = self._stream.read(num_frames, exception_on_overflow=False)
            if len(data) == 0:
                return ""

            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    return text
        except Exception as e:
            self.logger.error(f"ASRx[/︎︎] Error recognizing speech: {e}")
            # Handle specific error types
            if "Invalid handle" in str(e):
                self.logger.error(f"ASRx[/︎︎] Audio device error, attempting to reinitialize...")
                self.cleanup()
            return ""

        return ""

    def cleanup(self):
        """Clean up audio resources."""
        self._is_running = False

        if self._stream:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
                self._stream = None
            except Exception as e:
                self.logger.error(f"ASRx[/] Error closing audio stream: {e}")

        if self._audio_interface:
            try:
                self._audio_interface.terminate()
                self._audio_interface = None
            except Exception as e:
                self.logger.error(f"ASRx[/] Error terminating audio interface: {e}")

    @property
    def is_running(self) -> bool:
        """Check if the recognizer is currently running."""
        return self._is_running and self._stream and self._stream.is_active()


if __name__ == "__main__":
    recognizer = SpeechRecognizer()
    try:
        print("Speech recognition started. Speak into the microphone...")
        while True:
            recognized_text = recognizer.recognize()
            if recognized_text:
                print(f"Recognized: {recognized_text}")
    except KeyboardInterrupt:
        print("\nSpeech recognition stopped.")
        recognizer.cleanup()
