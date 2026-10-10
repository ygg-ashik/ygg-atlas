"""Keeps OAuth consent transaction ids out of uvicorn's access log.

A pending authorization's id (`txn`) is a bearer-like secret until it is consumed
(D36), and the consent API carries it in the path: `/api/v1/oauth/consent/{txn}`.
nginx redacts it on its side; this filter covers the backend container's own log.
"""

import logging
import re
from typing import Final

ACCESS_LOGGER: Final = "uvicorn.access"
_CONSENT_TXN: Final = re.compile(r"(/api/v1/oauth/consent/)[^/?#\s\"]+")
_REDACTED: Final = r"\1-"


def redact_consent_txn(text: str) -> str:
    """`text` with every consent path's transaction id replaced by `-`."""
    return _CONSENT_TXN.sub(_REDACTED, text)


class ConsentTxnRedactor(logging.Filter):
    """Rewrites the record's arguments (uvicorn passes the path as one) and message;
    never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_consent_txn(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_consent_txn(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def install_access_log_redaction() -> None:
    """Adds the filter to uvicorn's access logger once (idempotent)."""
    access = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, ConsentTxnRedactor) for f in access.filters):
        access.addFilter(ConsentTxnRedactor())
