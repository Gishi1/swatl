"""Repository hygiene checks.

These guard against packaging mistakes that unit tests cannot see: a source
file that exists locally but is excluded from the repository by ``.gitignore``
(or never added in the first place) passes every test on the developer's
machine and fails immediately for everyone else.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def git_repo():
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    if _git("rev-parse", "--git-dir").returncode != 0:
        pytest.skip("not a git checkout")
    return REPO_ROOT


def test_no_python_source_is_gitignored(git_repo):
    """A .gitignore pattern must never exclude real source or test files.

    Regression: an unanchored ``state/`` pattern also matched
    ``src/swatl/state/``, so the whole state package was missing from the
    published repository while every local test still passed.
    """
    result = _git("ls-files", "--others", "--ignored", "--exclude-standard", "--", "src", "tests")
    assert result.returncode == 0, result.stderr
    ignored = [line for line in result.stdout.splitlines() if line.endswith(".py")]
    assert ignored == [], f"source files are excluded by .gitignore: {ignored}"


def test_every_python_source_file_is_tracked(git_repo):
    """Every .py under src/ and tests/ must be known to git."""
    on_disk = {
        str(path.relative_to(REPO_ROOT))
        for path in list((REPO_ROOT / "src").rglob("*.py"))
        + list((REPO_ROOT / "tests").rglob("*.py"))
        if "__pycache__" not in path.parts
    }
    tracked = set(_git("ls-files", "--", "src", "tests").stdout.split())
    missing = sorted(on_disk - tracked)
    assert missing == [], f"files exist on disk but are not tracked by git: {missing}"


def test_package_modules_are_importable():
    """Every subpackage must import, so a missing directory is caught early."""
    import importlib

    for module in (
        "swatl",
        "swatl.audit",
        "swatl.context",
        "swatl.context_db",
        "swatl.ingest",
        "swatl.proofread",
        "swatl.providers",
        "swatl.quality",
        "swatl.review",
        "swatl.state",
        "swatl.translate",
        "swatl.web",
        "swatl.writeback",
    ):
        assert importlib.import_module(module) is not None


# APIs that exist only in Python 3.12+ while this package supports 3.11.
_PY312_ONLY = {
    # Path.walk() takes no arguments; os.walk(path) must not match.
    r"\.walk\(\s*\)": "pathlib.Path.walk is Python 3.12+ (use os.walk)",
    r"\bitertools\.batched\(": "itertools.batched is Python 3.12+",
    r"\btyping\.override\b": "typing.override is Python 3.12+",
    r"^\s*from typing import .*\boverride\b": "typing.override is Python 3.12+",
    r"@override\b": "typing.override is Python 3.12+",
}


@pytest.mark.parametrize("pattern,reason", sorted(_PY312_ONLY.items()))
def test_no_python_312_only_apis(pattern, reason):
    """`requires-python = ">=3.11"` must mean 3.11 actually works.

    Regression: `Path.walk()` silently broke every export on 3.11, which the
    3.12 development interpreter could never reveal.
    """
    import re

    compiled = re.compile(pattern)
    offenders = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if compiled.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    assert offenders == [], f"{reason}: {offenders}"
