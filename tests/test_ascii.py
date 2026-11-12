# SPDX-License-Identifier: GPL-3.0-or-later
"""Every text file in the repository is plain ASCII."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "site",
    "htmlcov",
    "test-results",
    "playwright-report",
}


def _files() -> list[Path]:
    """Tracked and new files from git; a plain walk where there is no checkout."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout.decode()
        return [ROOT / name for name in listed.split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        return [
            path
            for path in ROOT.rglob("*")
            if path.is_file() and not SKIP_DIRS.intersection(path.parts)
        ]


def test_text_files_are_ascii() -> None:
    offending: list[str] = []
    for path in _files():
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:  # binary (images)
            continue
        for number, line in enumerate(data.splitlines(), 1):
            if any(byte > 0x7F for byte in line):
                text = line.decode("utf-8", "replace").strip()
                offending.append(f"{path.relative_to(ROOT)}:{number}: {text[:80]}")
    assert not offending, "Non-ASCII text:\n" + "\n".join(offending)
