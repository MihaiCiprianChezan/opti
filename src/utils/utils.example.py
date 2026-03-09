import nltk

from utils.folders import Folders

nltk.data.path.append(Folders.nltk_data)
from nltk.tokenize import sent_tokenize
import logging
from pathlib import Path
import random
import re
from bs4 import BeautifulSoup
import keyboard
import mistune
import pyperclip
from utils.app_logger import AppLogger
from constants.regex import (
    CHINESE_CHARACTERS_REGEX,
    EMOJIS_REGEX,
    JAPANESE_CHARACTERS_REGEX,
    KOREAN_CHARACTERS_REGEX,
    MULTIPLE_SPACES_REGEX,
)

HF_TOKEN = "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"
MODELS_DIR = Path(__file__).parent.parent.parent / "models"
ALL_MINI_LM_L6_V2 = str(MODELS_DIR / "all-MiniLM-L6-v2")
VOSK_MODEL_SMALL_EN_US_0_15 = str(MODELS_DIR / "vosk-model-small-en-us-0.15")
VOSK_MODEL_EN_US_0_22_LGRAPH = str(MODELS_DIR / "vosk-model-en-us-0.22-lgraph")
CROSS_ENCODER_NLI_DISTILROBERTA_BASE = str(MODELS_DIR / "cross-encoder-nli-distilroberta-base")


def run_call_sync(func):
    """Run a callable function synchronously"""
    if func and callable(func):
        try:
            result = func()
            return result
        except Exception as e:
            logging.error(f"Error running function {func.__name__ if hasattr(func, '__name__') else str(func)}: {str(e)}")
            raise e


def get_parent_dir(path):
    return Path(path).parent


def get_key_for_value(value, dict):
    """Get the key for a given value in a dictionary."""
    return next((k for k, v in dict.items() if v == value), None)


class Utils:

    def __init__(self):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)

    def is_prompt_sane_and_valid(self, spoken, clean, min_tokens=2, min_chars=5, min_unique_tokens=2):
        """
        Validates if given spoken and clean prompt strings meet specified criteria.

        Args:
            spoken (str): The original spoken prompt text, may contain fillers or interjections.
            clean (str): The processed and cleaned prompt text for validation.
            min_tokens (int): Required minimum number of tokens in the `clean` text. Default is 2.
            min_chars (int): Required minimum number of characters in the `clean` text. Default is 3.
            min_unique_tokens (int): Required minimum number of unique tokens in the `clean` text.
                Default is 2.

        Returns:
            bool: True if the prompt passes all validation checks, otherwise False.
        """
        try:
            # Basic validation
            if not spoken and not clean:
                return False
            # Split into tokens and filter out fillers and interjections
            tokens = clean.split()
            unique_tokens = set(tokens)
            # Check basic content requirements (using meaningful tokens)
            if len(tokens) < min_tokens:
                return False
            if len(clean) < min_chars:
                return False
            if len(unique_tokens) < min_unique_tokens:
                return False
            # If we've passed all checks, the prompt is valid
            return True
        except Exception as e:
            self.logger.debug(f"Error validating prompt: {str(e)}")
            return False

    @staticmethod
    def get_unique_choice(options, last_choice=None):
        """Get a randomly selected option, avoiding the same choice as the last one."""
        if len(set(options)) <= 1:  # Guard to check if only one unique value exists
            return options[0]
        new_choice = random.choice(options)
        while new_choice == last_choice:
            new_choice = random.choice(options)
        return new_choice

    @staticmethod
    def clean_markdown_to_text(markdown_text):
        """
        Cleans the output from Markdown and extracts plain text efficiently.
        """
        renderer = mistune.create_markdown()
        html = renderer(markdown_text)
        plain_text = BeautifulSoup(html, "html.parser").get_text()
        return plain_text

    @staticmethod
    def clean_new_lines(plain_text):
        """Remove new lines from a string."""
        return plain_text.replace("\n", " ")

    @staticmethod
    def clean_multiple_spaces(plain_text):
        """Remove multiple spaces from a string."""
        return MULTIPLE_SPACES_REGEX.sub(" ", plain_text)

    def clean_nl_and_m_sp(self, plain_text):
        """Clean new lines and multiple spaces from a string."""
        plain_text = self.clean_new_lines(plain_text)
        plain_text = self.clean_multiple_spaces(plain_text)
        return plain_text.strip()

    def clean_incomplete(self, plain_text):
        """Cleans incomplete parts of a string."""
        punctuation_marks = (".", "!", "?", ";")
        cut_part = None
        if any(mark in plain_text for mark in punctuation_marks):
            if not plain_text.endswith(punctuation_marks):
                last_punctuation = max(plain_text.rfind("."), plain_text.rfind("!"), plain_text.rfind("?"), plain_text.rfind(";"))
                if last_punctuation != -1:
                    cut_part = plain_text[last_punctuation + 1 :].strip()
                    plain_text = plain_text[: last_punctuation + 1].strip()
        plain_text = plain_text.strip()
        if cut_part:
            self.logger.debug(f"[UTILS] Cleaned out incomplete part: {cut_part}")
        return plain_text

    @staticmethod
    def clean_emojis(plain_text):
        return EMOJIS_REGEX.sub("", plain_text)

    @staticmethod
    def is_eastern_asian(plain_text):
        return (
            (CHINESE_CHARACTERS_REGEX.search(plain_text))
            or (JAPANESE_CHARACTERS_REGEX.search(plain_text))
            or (KOREAN_CHARACTERS_REGEX.search(plain_text))
            or (JAPANESE_CHARACTERS_REGEX.search(plain_text))
        )

    def deep_text_clean(self, plain_text: str, clean_incomplete=False):
        if not plain_text:
            return ""
        # Preserve Chinese, Korean and Japanese characters and phrases ...
        if self.is_eastern_asian(plain_text):
            return plain_text
        # Make a deep clean of the text
        plain_text = self.clean_markdown_to_text(plain_text)
        plain_text = self.clean_new_lines(plain_text)
        plain_text = self.clean_multiple_spaces(plain_text)
        if clean_incomplete:
            plain_text = self.clean_incomplete(plain_text)
        plain_text = self.clean_emojis(plain_text)
        return plain_text.strip()

    @staticmethod
    def clean_text(text):
        """Clean the input text by removing non-alphanumeric characters."""
        single_spaced_text = MULTIPLE_SPACES_REGEX.sub(" ", text)
        return single_spaced_text.strip().lower()

    @staticmethod
    def paste_at_cursor():
        """Paste copied text at the cursor."""
        text = pyperclip.paste()
        keyboard.send(text)

    # @staticmethod
    # def write_text(text, delay=0.03):
    #     """Write the text dynamically with a slight delay."""
    #     keyboard.write(text, delay=delay)

    def ensure_path_exists(self, path):
        """
        Ensure the specified path exists:
        - If a file path, ensure the folder exists and create the file.
        - If a directory path, ensure it exists.
        """
        try:
            path_obj = Path(path)

            if path_obj.suffix:  # Check if it's a file
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                if not path_obj.exists():
                    path_obj.touch()
                    self.logger.debug(f"[UTILS] File created: {path_obj.resolve()}")
            else:  # It's a folder
                path_obj.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"[UTILS] Directory ensured: {path_obj.resolve()}")

        except Exception as e:
            self.logger.debug(f"[UTILS] Error ensuring path {path}: {e}")

    @staticmethod
    def extract_sentences_with_partial(text):
        """
        Split text into sentences using nltk.sent_tokenize, supporting English and Chinese punctuation.
        Returns (complete_sentences, partial_sentence).
        """
        if not text:
            return [], None
        end_markers = (".", "!", "?", "...", "…", "。", "！", "？", "؟", "۔", "।", "։", ";", "׃", "ฯ", "‼", "‽", "⋮")
        sentences = sent_tokenize(text)
        result = []
        for s in sentences:
            result.extend(re.split(r"(?<=。)", s))
        sentences = [s for s in result if s.strip()]
        if sentences and not sentences[-1].strip().endswith(end_markers):
            partial_sentence = sentences.pop().strip()
        else:
            partial_sentence = None
        return [s.strip() for s in sentences], partial_sentence

    def extract_all_sentences(self, text):
        sentences, partial = self.extract_sentences_with_partial(text)
        if partial:
            sentences.append(partial)
        return sentences
