"""Prax - Monitoring and logging for AIPass."""

try:
    from aipass.prax.apps.modules.logger import system_logger as logger
except Exception:
    # NullLogger fallback — branches must not crash if prax is broken.
    # Provides no-op info/warning/error so callers keep running.
    import logging as _logging

    class _NullLogger:
        """Fallback logger when prax SystemLogger fails to import."""

        def __init__(self):
            self._logger = _logging.getLogger("aipass.prax.fallback")
            if not self._logger.handlers:
                self._logger.addHandler(_logging.StreamHandler())
            self._logger.warning("Prax SystemLogger unavailable — using fallback NullLogger")

        def info(self, message, *args, **kwargs):
            self._logger.info(message, *args, **kwargs)

        def warning(self, message, *args, **kwargs):
            self._logger.warning(message, *args, **kwargs)

        def error(self, message, *args, **kwargs):
            self._logger.error(message, *args, **kwargs)

    logger = _NullLogger()
