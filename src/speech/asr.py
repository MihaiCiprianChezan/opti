import logging
import time
import traceback
from queue import Queue, Empty

from speech.recognizer import SpeechRecognizer
from utils.app_logger import AppLogger
from utils.threads import WorkerThread


class ASRx:
    """
    Manages the ASR service — runs SpeechRecognizer in a background thread,
    queuing recognized utterances for the shell to consume.
    Punctuation is handled natively by faster-whisper.
    """

    def __init__(self, queue: Queue = None):
        self.name = self.__class__.__name__
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.queue = queue or Queue(100)
        self.running = False
        self.thread = None
        self.recognizer = None
        self._stop_requested = False

    def initialize_sync(self):
        """Initialize the speech recognizer synchronously."""
        try:
            self.recognizer = SpeechRecognizer()
            self.logger.info("ASR initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize ASR: {e}, {traceback.format_exc()}")
            raise

    def start(self):
        """Start the ASR service in a background thread."""
        if self.thread and self.thread.is_alive():
            self.logger.debug("ASRxService[/] thread is already running.")
            return

        if not self.recognizer:
            self.initialize_sync()

        self.running = True
        self._stop_requested = False
        self.thread = WorkerThread(self.recognize, name="ASRxService")
        self.thread.start()
        self.logger.debug("ASRxService[/] thread has started.")

    def recognize(self):
        """Recognition loop — blocks per utterance, queues result."""
        self.logger.debug("ASRxService[/] task running.")

        while self.running and not self._stop_requested:
            try:
                if not self.recognizer:
                    time.sleep(0.05)
                    continue

                speech_to_text = self.recognizer.recognize()
                if speech_to_text:
                    self.queue.put(speech_to_text)
                    self.logger.debug(f"ASRxService[/] Queue: {list(self.queue.queue)}, < Recognized: `{speech_to_text}`")

            except Exception as e:
                self.logger.error(f"Error in ASRxService[/] thread: {e}, {traceback.format_exc()}")
                if "Invalid handle" in str(e):
                    self.logger.error("Audio device error, attempting to reinitialize...")
                    self.recognizer = None
                    try:
                        self.initialize_sync()
                    except Exception as init_error:
                        self.logger.error(f"Failed to reinitialize: {init_error}")
                        break

        self.logger.debug("ASRxService[/] task has stopped.")

    def stop(self):
        """Stop the ASR service."""
        if not self.thread:
            self.logger.debug("ASRxService[/] thread is not running.")
            return

        self._stop_requested = True
        self.running = False

        if self.thread.is_alive():
            self.thread.join()
            self.logger.debug("ASRxService[/] thread has fully stopped.")

    def get_next_input(self, timeout: float = None) -> str:
        try:
            return self.queue.get(timeout=timeout) if timeout else self.queue.get()
        except Empty:
            return ""

    @property
    def is_active(self) -> bool:
        return self.running and self.thread and self.thread.is_alive()


if __name__ == "__main__":
    asrx = ASRx()
    try:
        asrx.start()
        print("ASRx started. Press Ctrl+C to stop.")
        while True:
            if asrx.queue.qsize() > 0:
                print(f"Recognized: {asrx.queue.get()}")
    except KeyboardInterrupt:
        print("Stopping ASRx...")
        asrx.stop()
