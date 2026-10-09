"""Service-account emails are derived in identity, not in access (ruling C5)."""

import pytest

from app.identity import service_account_email


@pytest.mark.parametrize(
    ("name", "email"),
    [
        ("CI deploy", "svc-ci-deploy@atlas.internal"),
        ("  Nightly  Reports!! ", "svc-nightly-reports@atlas.internal"),
        ("etl_2026", "svc-etl-2026@atlas.internal"),
        ("abc", "svc-abc@atlas.internal"),
        ("x" * 40, f"svc-{'x' * 40}@atlas.internal"),
    ],
)
def test_service_account_email_is_a_slug(name: str, email: str) -> None:
    assert service_account_email(name) == email


@pytest.mark.parametrize("name", ["", "ab", "--", "!!!", "x" * 41, "é√ß"])
def test_service_account_names_need_3_to_40_slug_characters(name: str) -> None:
    assert service_account_email(name) is None
