"""Shared helpers for the test suite. Not a test module."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HUNT = REPO_ROOT / "skills" / "regression-hunt" / "scripts" / "hunt.py"
ARCHAEOLOGY = REPO_ROOT / "skills" / "blame-archaeology" / "scripts" / "archaeology.py"

ISOLATED_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


def git(cwd, *args):
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=ISOLATED_ENV,
    )
    if proc.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), proc.stderr))
    return proc.stdout.strip()


def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test Author")
    git(path, "config", "user.email", "author@example.com")
    return path


def commit(path, message, files):
    for name, content in files.items():
        target = Path(path) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        git(path, "add", name)
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD")


def run_script(script, args, cwd):
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=ISOLATED_ENV,
        timeout=180,
    )
    return proc.returncode, proc.stdout, proc.stderr
