"""Tests for the skill files themselves: spec conformance and importability."""

from __future__ import annotations

import py_compile
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import REPO_ROOT  # noqa: E402

SKILLS_ROOT = REPO_ROOT / "skills"
VALIDATOR = REPO_ROOT / "tools" / "validate_skills.py"


class SkillFilesTest(unittest.TestCase):
    def test_validator_passes(self):
        proc = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_skill_has_a_matching_directory_name(self):
        for skill_dir in sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir()):
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("name: %s" % skill_dir.name, text, skill_dir)

    def test_scripts_compile(self):
        for script in sorted(SKILLS_ROOT.glob("*/scripts/*.py")):
            py_compile.compile(str(script), doraise=True)

    def test_scripts_run_without_arguments(self):
        """A bare invocation must print usage and exit non-zero, not traceback."""
        for script in sorted(SKILLS_ROOT.glob("*/scripts/*.py")):
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0, script)
            self.assertNotIn("Traceback", proc.stderr, script)
            self.assertIn("usage:", proc.stderr.lower() + proc.stdout.lower(), script)


if __name__ == "__main__":
    unittest.main()
