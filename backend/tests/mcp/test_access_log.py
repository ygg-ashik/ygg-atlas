"""Consent transaction ids never reach uvicorn's access log (D36)."""

import logging
from collections.abc import Iterator

import pytest

from app import main
from app.mcp import install_access_log_redaction
from app.mcp.access_log import ACCESS_LOGGER, ConsentTxnRedactor, redact_consent_txn

TXN = "Qm9ndXNUeG5JZEZvclRlc3RpbmdPbmx5MTIzNDU2Nzg5"


@pytest.fixture
def access_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger(ACCESS_LOGGER)
    before = list(logger.filters)
    yield logger
    logger.filters[:] = before


def _record(path: str) -> logging.LogRecord:
    """An access record as uvicorn's httptools/h11 protocols build it."""
    return logging.LogRecord(
        ACCESS_LOGGER,
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "GET", path, "1.1", 200),
        None,
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"/api/v1/oauth/consent/{TXN}", "/api/v1/oauth/consent/-"),
        (f"/api/v1/oauth/consent/{TXN}?x=1", "/api/v1/oauth/consent/-?x=1"),
        ("/api/v1/oauth/consent", "/api/v1/oauth/consent"),
        ("/api/v1/me/tokens", "/api/v1/me/tokens"),
    ],
)
def test_redacts_the_consent_txn_path_segment(path: str, expected: str) -> None:
    assert redact_consent_txn(path) == expected


def test_installed_filter_rewrites_uvicorn_access_records(
    access_logger: logging.Logger,
) -> None:
    install_access_log_redaction()
    install_access_log_redaction()  # idempotent
    assert sum(isinstance(f, ConsentTxnRedactor) for f in access_logger.filters) == 1

    record = _record(f"/api/v1/oauth/consent/{TXN}")
    assert access_logger.filter(record)

    message = record.getMessage()
    assert TXN not in message
    assert '"GET /api/v1/oauth/consent/- HTTP/1.1" 200' in message


def test_other_records_pass_through_unchanged(access_logger: logging.Logger) -> None:
    install_access_log_redaction()
    record = _record("/api/v1/chat")
    assert access_logger.filter(record)
    assert record.getMessage() == '10.0.0.1:5000 - "GET /api/v1/chat HTTP/1.1" 200'


def test_main_installs_the_filter() -> None:
    assert main.app is not None  # importing main installs the filter
    access = logging.getLogger(ACCESS_LOGGER)
    assert any(isinstance(f, ConsentTxnRedactor) for f in access.filters)
