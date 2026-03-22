import json
import logging
import datetime
from typing import Any, Dict

class StructuredLogger:
    """
    Standardized logger for dataproc-engine that outputs JSON for machine-readability.
    """
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name

    def _log(self, level: int, event: str, **kwargs):
        log_entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "level": logging.getLevelName(level),
            "logger": self.name,
            "event": event,
            **kwargs
        }
        self.logger.log(level, json.dumps(log_entry))

    def info(self, event: str, **kwargs):
        self._log(logging.INFO, event, **kwargs)

    def error(self, event: str, **kwargs):
        self._log(logging.ERROR, event, **kwargs)

    def warning(self, event: str, **kwargs):
        self._log(logging.WARNING, event, **kwargs)

    def critical(self, event: str, **kwargs):
        self._log(logging.CRITICAL, event, **kwargs)
