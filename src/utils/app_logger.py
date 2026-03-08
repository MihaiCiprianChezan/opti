import logging
import traceback
from pathlib import Path

from utils.folders import Folders


class ColorFormatter(logging.Formatter):
    COLORS = {
        # logging.DEBUG: "\033[36m",     # Cyan
        logging.DEBUG: "\033[90m",  # Grey
        logging.INFO: "\033[32m",  # Green
        logging.WARNING: "\033[33m",  # Yellow
        logging.ERROR: "\033[31m",  # Red
        logging.CRITICAL: "\033[48;5;160m\033[38;5;226m",  # Red background
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        message = super().format(record)
        return f"{color}{message}{self.RESET}"


class AppLogger:
    _instances = {}  # Store logger instances by name
    _paused = False  # Global paused state for ALL logger instances
    _cached_logs = []  # Shared global log cache
    _default_logger_name = "AppLogger"
    _default_overwrite = True
    _default_log_level = logging.DEBUG
    _default_file_name = Path(Folders.log) / "app.log"

    def __new__(cls, name=None, *args, **kwargs):
        # If no name provided, use the default name
        if name is None:
            name = cls._default_logger_name
            
        # Create a new instance if it doesn't exist
        if name not in cls._instances:
            instance = super().__new__(cls)
            instance._initialize(name, *args, **kwargs)
            cls._instances[name] = instance
            
        return cls._instances[name]

    def _initialize(self, name, file_name=None, overwrite=None, log_level=None):
        """Initialize a new logger instance"""
        self.name = name
        self.file_name = Path(Folders.log) / Path(file_name) if file_name else self._default_file_name
        self.overwrite = overwrite if overwrite is not None else self._default_overwrite
        self.log_level = log_level if log_level is not None else self._default_log_level
        
        # Create logger with the given name
        self._logger = logging.getLogger(name)
        self._logger.setLevel(self.log_level)
        self._logger.propagate = False  # Prevent duplicate logs from parent loggers
        
        # Configure handlers if this is the first time this logger is initialized
        if not self._logger.handlers:
            self._configure_handlers()
            
        self._initialized = True

    def _configure_handlers(self):
        """Configure handlers for the logger"""
        # Clear any existing handlers
        for handler in self._logger.handlers[:]:
            self._logger.removeHandler(handler)
            handler.close()
            
        # File handler
        file_mode = "w" if self.overwrite else "a"
        file_handler = logging.FileHandler(
            self.file_name, 
            mode=file_mode, 
            encoding="utf-8", 
            delay=True, 
            errors="ignore"
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s"))
        
        # Console handler with color
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ColorFormatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s"))
        
        # Add handlers
        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """Return the shared logger instance."""
        if cls._instance:
            return cls._instance._logger
        raise RuntimeError("AppLogger has not been initialized.")

    @classmethod
    def pause(cls):
        """Globally pause logging for all instances."""
        cls._paused = True
        
    @classmethod
    def resume(cls):
        """
        Globally resume logging for all instances and flush cached logs.
        Cached log messages are handled in the order they were received.
        """
        if cls._paused:
            cls._paused = False
            # Flush cached logs
            for record in cls._cached_logs:
                # Try to find the appropriate logger for each record
                logger_name = getattr(record, 'name', None)
                if logger_name and logger_name in cls._instances:
                    cls._instances[logger_name]._logger.handle(record)
            cls._cached_logs.clear()

    def log(self, level, message):
        """
        Log a message:
        - If logger is globally paused, cache the log message.
        - Otherwise, emit the log immediately.
        """
        if self._paused:
            # Create a log record and cache it
            record = self._logger.makeRecord(self._logger.name, level, None, None, message, None, None)
            self._cached_logs.append(record)
        else:
            self._logger.log(level, message)
            
    def get_child(self, suffix):
        """
        Get a child logger with the given suffix.
        The name of the child logger will be 'parent_name.suffix'.
        """
        child_name = f"{self.name}.{suffix}"
        return AppLogger(name=child_name)

    # Convenience methods for commonly used log levels
    def info(self, message):
        self.log(logging.INFO, "%s" % message)

    def debug(self, message):
        self.log(logging.DEBUG, "%s" % message)

    def warning(self, message):
        self.log(logging.WARNING, "<!> %s" % message)

    def error(self, message, exception=None):
        """
        Intelligent error logging - automatically handles exceptions and tracebacks
        
        Args:
            message: The error message
            exception: Optional exception object. If provided, includes exception details and traceback
        """
        if exception:
            error_msg = f"{message}: {exception}, {traceback.format_exc()}"
        else:
            error_msg = message
        self.log(logging.ERROR, "<<!>> %s" % error_msg)

    def critical(self, message, exception=None):
        """
        Intelligent critical logging - automatically handles exceptions and tracebacks
        
        Args:
            message: The critical error message
            exception: Optional exception object. If provided, includes exception details and traceback
        """
        if exception:
            error_msg = f"{message}: {exception}, {traceback.format_exc()}"
        else:
            error_msg = message
        self.log(logging.CRITICAL, "<<<!>>> %s" % error_msg)

    def set_level(self, level):
        """
        Set the log level for this logger instance
        
        Args:
            level: Logging level (e.g., logging.DEBUG, logging.INFO)
        """
        self._logger.setLevel(level)
        for handler in self._logger.handlers:
            handler.setLevel(level)
        self._logger.debug(f"Log level updated to: {logging.getLevelName(level)}")
        
    @classmethod
    def get_logger(cls, name):
        """Get a logger instance by name"""
        return cls._instances.get(name)
        
    @classmethod
    def set_level_for_all(cls, level):
        """Set log level for all existing loggers"""
        for logger in cls._instances.values():
            logger.set_level(level)

    def get_current_log_level(self) -> str:
        """
        Get the current logging level as a human-readable name.

        Returns:
            str: The current logging level (e.g., "DEBUG", "INFO").
        """
        return logging.getLevelName(self._logger.level)
