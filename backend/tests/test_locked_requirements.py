"""The audit export must resolve platform markers for the right environment."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

X86_MAC = "sys_platform == 'darwin' and platform_machine == 'x86_64'"
NOT_X86_MAC = "sys_platform != 'darwin' or platform_machine != 'x86_64'"
LINES = [f"cryptography==48.0.1 ; {X86_MAC}", f"cryptography==50.0.2 ; {NOT_X86_MAC}"]


def _load_script() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "locked_requirements.py"
    spec = importlib.util.spec_from_file_location("locked_requirements", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_keeps_unmarked_pins_and_skips_comments() -> None:
    pins = _load_script().platform_pins(
        ["# generated", "", "-e .", "fastapi==0.115.0", "pyjwt==2.15.1\n"]
    )
    assert pins == ["fastapi==0.115.0", "pyjwt==2.15.1"]


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({"sys_platform": "linux", "platform_machine": "x86_64"}, "50.0.2"),
        ({"sys_platform": "darwin", "platform_machine": "arm64"}, "50.0.2"),
        ({"sys_platform": "darwin", "platform_machine": "x86_64"}, "48.0.1"),
    ],
)
def test_resolves_markers_per_environment(
    environment: dict[str, str], expected: str
) -> None:
    assert _load_script().platform_pins(LINES, environment) == [
        f"cryptography=={expected}"
    ]


def test_rejects_hashed_export() -> None:
    with pytest.raises(ValueError, match="hashed export"):
        _load_script().platform_pins(["fastapi==0.115.0 \\", "    --hash=sha256:abc"])
