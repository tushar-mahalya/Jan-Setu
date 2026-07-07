"""Correlation-id propagation for structured logs.

Set once per request (``app.py`` middleware) or per background unit of work
(``worker.py``); every log call anywhere in that call chain then carries it via
a ``logging.Filter``, without threading ``request_id`` through every function
signature in ``processing.py``/``pipeline.py``.
"""

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = request_id_var.get()
        return True
