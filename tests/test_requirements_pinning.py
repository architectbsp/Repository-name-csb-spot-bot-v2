"""
Regression guard for B29: every dependency in requirements.txt must be
pinned to an exact version so a fresh `pip install -r requirements.txt`
cannot silently pull in a breaking upstream release.
"""

from pathlib import Path

REQUIREMENTS_PATH = Path(__file__).resolve().parents[1] / "requirements.txt"


def _requirement_lines() -> list[str]:
    lines = REQUIREMENTS_PATH.read_text().splitlines()
    return [line.strip() for line in lines if line.strip()]


def test_requirements_file_is_not_empty():
    assert _requirement_lines()


def test_every_dependency_is_pinned_to_an_exact_version():
    unpinned = [line for line in _requirement_lines() if "==" not in line]

    assert unpinned == [], (
        f"Found unpinned dependencies in requirements.txt: {unpinned}"
    )


def test_expected_dependencies_are_present_and_pinned():
    lines = _requirement_lines()
    names = {line.split("==")[0].lower() for line in lines}

    for expected in (
        "ccxt",
        "python-dotenv",
        "websocket-client",
        "sqlalchemy",
        "flet",
    ):
        assert expected in names, f"Missing dependency: {expected}"
