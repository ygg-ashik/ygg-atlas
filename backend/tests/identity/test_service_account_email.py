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


@pytest.mark.parametrize(
    "name", ["", "ab", "--", "!!!", "x" * 41, "é√ß", "a" + "!" * 300 + "b"]
)
def test_service_account_names_need_3_to_40_slug_characters(name: str) -> None:
    assert service_account_email(name) is None


def test_names_over_100_characters_are_refused_even_with_a_short_slug() -> None:
    assert service_account_email("a" * 3 + " " * 98) is not None  # stripped to 3
    assert service_account_email("a" + "-" * 99) is None  # slug "a": too short
    assert service_account_email("ab" + "!" * 98 + "c") is None  # 101 characters
    assert service_account_email("ab" + "!" * 97 + "c") == "svc-ab-c@atlas.internal"
