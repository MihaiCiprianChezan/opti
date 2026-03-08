"""
TextCleaner — extracted text cleaning pipeline from Utils.

Dependencies: mistune, beautifulsoup4, constants.regex
No nltk, no keyboard, no pyperclip.
"""
import logging

from bs4 import BeautifulSoup
import mistune

from constants.regex import (
    CHINESE_CHARACTERS_REGEX,
    EMOJIS_REGEX,
    JAPANESE_CHARACTERS_REGEX,
    KOREAN_CHARACTERS_REGEX,
    MULTIPLE_SPACES_REGEX,
)
from utils.app_logger import AppLogger


class TextCleaner:

    def __init__(self):
        self.logger = AppLogger(name=self.__class__.__name__, log_level=logging.DEBUG)

    @staticmethod
    def clean_markdown_to_text(markdown_text):
        """Cleans the output from Markdown and extracts plain text efficiently."""
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
            self.logger.debug(f"Cleaned out incomplete part: {cut_part}")
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
        # Preserve Chinese, Korean and Japanese characters and phrases
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
