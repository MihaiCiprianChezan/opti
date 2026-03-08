"""
OutputDigester — converts verbose CLI agent output into speakable voice updates.

Two modes:
  1. Incremental progress: pattern-based detection of milestones (files, tests, installs, errors)
  2. Final summary: always LLM-summarized for natural spoken output
"""
import re
import time
import logging
import traceback
from typing import Callable

from utils.app_logger import AppLogger

# --- Progress detection patterns ---
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # File operations
    (re.compile(r'(?:Reading|Viewing|Opening)\s+(?:file\s+)?(.+)', re.IGNORECASE), "Reading {0}."),
    (re.compile(r'(?:Editing|Modifying|Updating|Writing)\s+(?:file\s+)?(.+)', re.IGNORECASE), "Editing {0}."),
    (re.compile(r'(?:Created|Creating)\s+(?:file\s+)?(.+)', re.IGNORECASE), "Created {0}."),
    (re.compile(r'(?:Deleted|Removing|Removed)\s+(.+)', re.IGNORECASE), "Removed {0}."),

    # Tests
    (re.compile(r'(\d+)\s+tests?\s+passed', re.IGNORECASE), "{0} tests passed."),
    (re.compile(r'(\d+)\s+tests?\s+failed', re.IGNORECASE), "{0} tests failed."),
    (re.compile(r'(?:Running|Executing)\s+tests?', re.IGNORECASE), "Running tests."),
    (re.compile(r'All\s+tests\s+pass', re.IGNORECASE), "All tests passed."),

    # Installation
    (re.compile(r'(?:npm|pip|yarn|pnpm)\s+install', re.IGNORECASE), "Installing dependencies."),
    (re.compile(r'Installing\s+(.+)', re.IGNORECASE), "Installing {0}."),

    # Git operations
    (re.compile(r'(?:Committing|committed)', re.IGNORECASE), "Making a commit."),
    (re.compile(r'(?:Pushing|pushed)\s+to', re.IGNORECASE), "Pushing to remote."),

    # Build/compile
    (re.compile(r'(?:Building|Compiling)', re.IGNORECASE), "Building the project."),
    (re.compile(r'Build\s+(?:succeeded|successful|complete)', re.IGNORECASE), "Build succeeded."),

    # Errors
    (re.compile(r'^(?:Error|ERROR|FATAL):\s*(.+)', re.IGNORECASE), "Error: {0}."),

    # Completion signals
    (re.compile(r'(?:Done|Complete|Finished|Success)[\.\!\s]*$', re.IGNORECASE), "Task complete."),
]

# Max output chars to send to the summarizer LLM
_MAX_SUMMARY_INPUT = 4000

_SUMMARIZE_PROMPT = (
    "Summarize the following CLI agent output in 1-3 conversational sentences "
    "suitable for text-to-speech. Focus on what was accomplished, key results, "
    "and any errors. Be concise and natural — this will be spoken aloud.\n\n"
    "Output:\n{output}"
)


class OutputDigester:
    """
    Digests verbose CLI output into speakable progress updates and a final summary.

    Args:
        summarizer: Callable that takes a prompt string and returns an LLM-generated summary.
                    Injected to keep the digester decoupled from any specific adapter.
        progress_interval: Minimum seconds between progress updates (default 5).
    """

    def __init__(self, summarizer: Callable[[str], str] | None = None, progress_interval: float = 5.0):
        self._summarizer = summarizer
        self._progress_interval = progress_interval
        self._last_progress_time: float = 0
        self._last_progress_text: str = ""
        self._logger = AppLogger(name="OutputDigester", log_level=logging.DEBUG)

    def feed_line(self, line: str) -> str | None:
        """
        Feed a raw CLI output line. Returns a speakable progress string
        if a milestone is detected and rate limit allows, else None.
        """
        now = time.time()
        if now - self._last_progress_time < self._progress_interval:
            return None

        for pattern, template in _PATTERNS:
            match = pattern.search(line)
            if match:
                # Extract just the filename from paths
                groups = [self._shorten_path(g) for g in match.groups()]
                progress = template.format(*groups) if groups else template
                # Deduplicate consecutive identical progress
                if progress == self._last_progress_text:
                    return None
                self._last_progress_time = now
                self._last_progress_text = progress
                return progress

        return None

    def get_summary(self, full_output: str) -> str:
        """
        Produce a spoken summary of the full CLI output using the injected LLM summarizer.
        Falls back to truncated output if no summarizer is available.
        """
        if not full_output.strip():
            return "The command completed with no output."

        # Truncate for LLM token limits
        truncated = full_output[-_MAX_SUMMARY_INPUT:] if len(full_output) > _MAX_SUMMARY_INPUT else full_output
        prompt = _SUMMARIZE_PROMPT.format(output=truncated)

        if self._summarizer:
            try:
                summary = self._summarizer(prompt)
                if summary and summary.strip():
                    return summary.strip()
            except Exception as e:
                self._logger.error(f"Summarizer failed: {e}, {traceback.format_exc()}")

        # Fallback: return last meaningful lines
        return self._fallback_summary(full_output)

    def reset(self) -> None:
        """Reset state for a new CLI invocation."""
        self._last_progress_time = 0
        self._last_progress_text = ""

    @staticmethod
    def _shorten_path(path: str) -> str:
        """Shorten a file path to just the filename for speakability."""
        path = path.strip().rstrip('.')
        # Extract just the filename if it looks like a path
        if '/' in path or '\\' in path:
            return path.replace('\\', '/').rsplit('/', 1)[-1]
        return path

    @staticmethod
    def _fallback_summary(output: str) -> str:
        """Extract last few meaningful lines as a basic summary."""
        lines = [l.strip() for l in output.strip().splitlines() if l.strip()]
        if not lines:
            return "The command finished."
        # Take last 3 non-empty lines
        tail = lines[-3:]
        return " ".join(tail)[:300]
