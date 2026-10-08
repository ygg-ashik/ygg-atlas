import pytest

from app.access.patterns import InvalidPatternError, matches, validate_pattern


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("*", "demo/order/revenue", True),
        ("*", "demo/order", True),
        ("demo/*", "demo/order/revenue", True),
        ("demo/*", "demo/order", True),
        ("demo/*", "demo", True),
        ("demo/order/*", "demo/order/revenue", True),
        ("demo/order/*", "demo/order", True),
        ("demo/order/*", "demo/checkout/checkout_funnel", False),
        ("demo/order/revenue", "demo/order/revenue", True),
        ("demo/order/revenue", "demo/order/aov", False),
        ("demo/*/revenue", "demo/order/revenue", True),
        ("demo/*/revenue", "demo/order/aov", False),
        ("deepsales/*", "demo/order/revenue", False),
        ("demo/order", "demo/order", True),
        ("demo/order", "demo/order/revenue", False),
    ],
)
def test_matches(pattern: str, path: str, expected: bool) -> None:
    assert matches(pattern, path) is expected


@pytest.mark.parametrize(
    "pattern", ["*", "deepsales/*", "demo/order/revenue", "demo/*/revenue"]
)
def test_valid_patterns(pattern: str) -> None:
    assert validate_pattern(pattern) == pattern


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        "demo//x",
        "Demo/*",
        "demo/order/revenue/x",
        "demo/*x",
        "demo/a b",
        "../x",
        "demo",
        "demo/order",
    ],
)
def test_invalid_patterns(pattern: str) -> None:
    with pytest.raises(InvalidPatternError):
        validate_pattern(pattern)


def test_entity_pattern_error_suggests_trailing_star() -> None:
    with pytest.raises(InvalidPatternError, match=r"demo/order/\*"):
        validate_pattern("demo/order")
