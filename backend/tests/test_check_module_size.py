"""The module size gate reports exactly the modules and classes over its limits."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_script() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "check_module_size.py"
    spec = importlib.util.spec_from_file_location("check_module_size", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _load_script()


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _lines(count: int) -> str:
    return "x = 1\n" * count


def _class_with(name: str, methods: int) -> str:
    body = "".join(f"    def m{i}(self) -> None: ...\n" for i in range(methods))
    return f"class {name}:\n{body}"


def _clean_tree(root: Path) -> None:
    _write(root, "app/at_limit.py", _lines(500))
    _write(root, "app/twenty.py", _class_with("Twenty", 20))
    _write(root, "tests/test_at_limit.py", _lines(800))
    # Exempt: generated or vendored code is never measured.
    _write(root, "app/migrations/versions/big.py", _lines(900))
    _write(root, "app/__pycache__/big.py", _lines(900))
    _write(root, "tests/migrations/big.py", _class_with("Huge", 30) + _lines(900))


def _violating_tree(root: Path) -> None:
    _clean_tree(root)
    _write(root, "app/too_long.py", _lines(501))
    _write(root, "app/pkg/wide.py", _class_with("Wide", 21))
    _write(root, "tests/test_too_long.py", _lines(801))
    # Tests may hold 501..800 lines and are never checked for class width.
    _write(root, "tests/test_medium.py", _class_with("Many", 25) + _lines(600))


def _reported(root: Path) -> set[str]:
    return {str(v) for v in SCRIPT.collect(root)}


def test_a_tree_at_the_limits_has_no_violations(tmp_path: Path) -> None:
    _clean_tree(tmp_path)

    assert _reported(tmp_path) == set()


def test_reports_exactly_the_modules_and_classes_over_their_limits(
    tmp_path: Path,
) -> None:
    _violating_tree(tmp_path)

    assert _reported(tmp_path) == {
        "app/too_long.py: 501 lines (limit 500)",
        "app/pkg/wide.py: class Wide has 21 methods (limit 20)",
        "tests/test_too_long.py: 801 lines (limit 800)",
    }


def test_async_methods_count_toward_the_class_limit(tmp_path: Path) -> None:
    sync = "".join(f"    def s{i}(self) -> None: ...\n" for i in range(11))
    other = "".join(f"    async def a{i}(self) -> None: ...\n" for i in range(10))
    _write(tmp_path, "app/mixed.py", f"class Mixed:\n{sync}{other}")

    assert _reported(tmp_path) == {
        "app/mixed.py: class Mixed has 21 methods (limit 20)"
    }


def test_strict_mode_fails_on_violations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _violating_tree(tmp_path)

    assert SCRIPT.main([], tmp_path) == 1
    assert "module size: 3 violation(s)" in capsys.readouterr().err


def test_warn_mode_reports_but_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _violating_tree(tmp_path)

    assert SCRIPT.main(["--warn"], tmp_path) == 0
    assert "app/too_long.py: 501 lines (limit 500)" in capsys.readouterr().err


def test_a_clean_tree_passes_in_strict_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_tree(tmp_path)

    assert SCRIPT.main([], tmp_path) == 0
    assert capsys.readouterr().out == "module size: ok\n"
