"""Turn `uv export` output into marker-free pins for one target environment.

pip-audit evaluates environment markers against its OWN isolated interpreter (via
uvx), not the project venv. Those can differ: on an M1 with an x86_64 project
Python under Rosetta, pip-audit's arm64 interpreter would audit the arm64 pin and
miss the x86_64 one that is actually installed. This resolves each marker for the
interpreter running this script (the project venv) or an explicit environment, and
keeps only matching pins, still sourced from uv.lock.

Usage:
    uv export --no-dev --no-hashes --no-emit-project --format requirements-txt \
        | uv run python scripts/locked_requirements.py > requirements-audit.txt
"""

import sys
from collections.abc import Iterable

from packaging.markers import Marker


def platform_pins(
    lines: Iterable[str], environment: dict[str, str] | None = None
) -> list[str]:
    """Pins whose markers match `environment` (default: this interpreter)."""
    pins: list[str] = []
    for raw in lines:
        line = raw.strip()
        if line.endswith("\\"):
            msg = "hashed export detected: run `uv export` with --no-hashes"
            raise ValueError(msg)
        if not line or line.startswith(("#", "-")):
            continue
        requirement, _, marker = line.partition(";")
        if marker.strip() and not Marker(marker.strip()).evaluate(environment):
            continue
        pins.append(requirement.strip())
    return pins


def main() -> None:
    sys.stdout.write("\n".join(platform_pins(sys.stdin)) + "\n")


if __name__ == "__main__":
    main()
