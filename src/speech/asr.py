import logging
import time
import traceback
from queue import Queue, Empty

from fastpunct import FastPunct

from speech.recognizer import SpeechRecognizer
from utils.app_logger import AppLogger
from utils.threads import WorkerThread


class ASRx:
    """
    The `ASRx` class manages the Automatic Speech Recognition (ASR) functionality.

    This class is responsible for setting up and managing the ASR system, including initializing the recognizer,
    starting a worker thread to continuously listen for speech, and handling the recognized text.
    """

    def __init__(self, queue: Queue = None):
        """
        Initializes a new instance of the ASRx class.

        Args:
            queue (Queue, optional): A queue used to store recognized speech. Defaults to a new Queue with a size limit of 100.

        Attributes:
            name (str): The name of the class.
            logger (AppLogger): Logger instance for logging messages.
            queue (Queue): Queue for storing recognized speech.
            running (bool): Indicates whether the ASR service is running.
            thread (WorkerThread, optional): WorkerThread that runs the recognition loop.
            recognizer (SpeechRecognizer): Instance responsible for performing speech recognition.

        """
        self.name = self.__class__.__name__
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)
        self.queue = queue or Queue(100)  # Queue for recognized speech
        self.running = False
        self.thread = None
        self.recognizer = None
        self._stop_requested = False
        self._fastpunct = None

    def initialize_sync(self):
        """Initialize the speech recognizer and punctuation restorer synchronously"""
        try:
            self.recognizer = SpeechRecognizer()
            self.logger.info("ASR initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize ASR: {e}")
            raise

        try:
            self._fastpunct = FastPunct()
            self.logger.info("FastPunct punctuation restorer initialized successfully")
        except Exception as e:
            self.logger.warning(f"FastPunct unavailable, punctuation will not be restored: {e}, {traceback.format_exc()}")
            self._fastpunct = None

    def _restore_punctuation(self, text: str) -> str:
        """Restore punctuation to raw ASR text using FastPunct. Falls back to original on failure."""
        if not self._fastpunct:
            return text
        try:
            results = self._fastpunct.punct([text])
            return results[0] if results else text
        except Exception as e:
            self.logger.warning(f"Punctuation restoration failed, using raw text: {e}")
            return text

    def start(self):
        """Start the ASR service in a background thread"""
        if self.thread and self.thread.is_alive():
            self.logger.debug(f"ASRxService[/] thread is already running.")
            return

        if not self.recognizer:
            self.initialize_sync()

        self.running = True
        self._stop_requested = False
        self.thread = WorkerThread(self.recognize, name="ASRxService")
        self.thread.start()
        self.logger.debug(f"ASRxService[/] thread has started.")

    def recognize(self):
        """Recognition loop that runs in its own thread"""
        self.logger.debug(f"ASRxService[/] task running.")

        while self.running and not self._stop_requested:
            try:
                if not self.recognizer:
                    # Wait for initialization to complete
                    time.sleep(0.05)
                    continue

                speech_to_text = self.recognizer.recognize()
                if speech_to_text:
                    speech_to_text = self._restore_punctuation(speech_to_text)
                    self.queue.put(speech_to_text)
                    self.logger.debug(
                        f"ASRxService[/] Queue: {list(self.queue.queue)}, < Recognized: `{speech_to_text}`"
                    )

            except Exception as e:
                self.logger.error(f"Error in ASRxService[/] thread: {e}, {traceback.format_exc()}")
                if "Invalid handle" in str(e):
                    # Handle audio device errors
                    self.logger.error(f"Audio device error, attempting to reinitialize...")
                    self.recognizer = None
                    try:
                        self.initialize_sync()
                    except Exception as init_error:
                        self.logger.error(f"Failed to reinitialize: {init_error}")
                        break

        self.logger.debug(f"ASRxService[/] task has stopped.")

    def stop(self):
        """Stop the ASR service"""
        if not self.thread:
            self.logger.debug(f"ASRxService[/] thread is not running.")
            return

        self._stop_requested = True
        self.running = False

        if self.thread.is_alive():
            self.thread.join()
            self.logger.debug(f"ASRxService[/] thread has fully stopped.")

    def get_next_input(self, timeout: float = None) -> str:
        """
        Get the next recognized speech input.

        Args:
            timeout (float, optional): Maximum time to wait for input in seconds.

        Returns:
            str: The recognized text, or empty string if timeout occurs.
        """
        try:
            if timeout:
                return self.queue.get(timeout=timeout)
            return self.queue.get()
        except Empty:
            return ""

    @property
    def is_active(self) -> bool:
        """Check if the ASR service is actively running"""
        return self.running and self.thread and self.thread.is_alive()


if __name__ == "__main__":
    asrx = ASRx()
    try:
        asrx.start()
        print("ASRx started. Press Ctrl+C to stop.")
        while True:
            if asrx.queue.qsize() > 3:
                recognized_text = asrx.queue.get()
                print(f"Recognized: {recognized_text}")
    except KeyboardInterrupt:
        print("Stopping ASRx...")
        asrx.stop()
