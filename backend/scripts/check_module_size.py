"""Module and class size gate (ARCHITECTURE.md §2.4).

Ruff has no file-length rule, so this script is the backend's size check. It is
run by `make check-backend` and CI.

    uv run python scripts/check_module_size.py           # fail on any violation
    uv run python scripts/check_module_size.py --warn    # report only, exit 0
"""

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

APP_MODULE_MAX_LINES = 500
TEST_MODULE_MAX_LINES = 800
CLASS_MAX_METHODS = 20

BACKEND = Path(__file__).resolve().parent.parent
EXEMPT_PARTS = frozenset({"migrations", "__pycache__", ".venv"})


@dataclass(frozen=True, slots=True)
class Violation:
    path: Path
    what: str

    def __str__(self) -> str:
        return f"{self.path.relative_to(BACKEND)}: {self.what}"


def _python_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.py") if not EXEMPT_PARTS.intersection(p.parts)
    )


def _line_violation(path: Path, limit: int) -> Violation | None:
    lines = len(path.read_text(encoding="utf-8").splitlines())
    if lines <= limit:
        return None
    return Violation(path, f"{lines} lines (limit {limit})")


def _class_violations(path: Path) -> list[Violation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = sum(
            isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            for item in node.body
        )
        if methods > CLASS_MAX_METHODS:
            out.append(
                Violation(
                    path,
                    f"class {node.name} has {methods} methods "
                    f"(limit {CLASS_MAX_METHODS})",
                )
            )
    return out


def collect() -> list[Violation]:
    """Every size violation under app/ and tests/."""
    found: list[Violation] = []
    for path in _python_files(BACKEND / "app"):
        if v := _line_violation(path, APP_MODULE_MAX_LINES):
            found.append(v)
        found.extend(_class_violations(path))
    for path in _python_files(BACKEND / "tests"):
        if v := _line_violation(path, TEST_MODULE_MAX_LINES):
            found.append(v)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warn", action="store_true", help="report, never fail")
    args = parser.parse_args()
    violations = collect()
    for v in violations:
        print(v, file=sys.stderr)
    if not violations:
        print("module size: ok")
        return 0
    print(f"module size: {len(violations)} violation(s)", file=sys.stderr)
    return 0 if args.warn else 1


if __name__ == "__main__":
    raise SystemExit(main())
