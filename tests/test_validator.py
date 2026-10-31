"""Unit tests for tools/validate_skills.py.

The validator is the repository's guard rail, so it is tested against the
failures it is supposed to catch, not only against the skills that exist.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tools"))
import validate_skills as vs  # noqa: E402

LONG_DESCRIPTION = (
    "Extracts text and tables from PDF files, fills forms, and merges documents. "
    "Use when the user mentions PDFs or document extraction."
)


class ValidatorTest(unittest.TestCase):
    def skill(self, frontmatter, body="# Skill\n\nDo the thing.\n", name="demo-skill"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name) / name
        directory.mkdir()
        (directory / "SKILL.md").write_text("---\n" + frontmatter + "\n---\n" + body)
        return directory

    def test_accepts_a_minimal_skill(self):
        directory = self.skill("name: demo-skill\ndescription: " + LONG_DESCRIPTION)
        self.assertEqual(vs.validate_skill(directory), [])

    def test_rejects_a_name_that_does_not_match_the_directory(self):
        directory = self.skill("name: other-skill\ndescription: " + LONG_DESCRIPTION)
        errors = vs.validate_skill(directory)
        self.assertTrue(any("does not match its directory" in e for e in errors), errors)

    def test_rejects_uppercase_and_double_hyphens(self):
        for bad in ("Demo-Skill", "demo--skill", "-demo", "demo_skill"):
            directory = self.skill("name: %s\ndescription: %s" % (bad, LONG_DESCRIPTION), name=bad)
            errors = vs.validate_skill(directory)
            self.assertTrue(any("must be lowercase" in e for e in errors), (bad, errors))

    def test_rejects_a_short_description(self):
        directory = self.skill("name: demo-skill\ndescription: Helps with PDFs.")
        errors = vs.validate_skill(directory)
        self.assertTrue(any("too short to route on" in e for e in errors), errors)

    def test_rejects_a_long_description(self):
        directory = self.skill("name: demo-skill\ndescription: " + "x" * 1030)
        errors = vs.validate_skill(directory)
        self.assertTrue(any("maximum is 1024" in e for e in errors), errors)

    def test_rejects_a_missing_description(self):
        directory = self.skill("name: demo-skill")
        errors = vs.validate_skill(directory)
        self.assertTrue(any("missing required field 'description'" in e for e in errors), errors)

    def test_rejects_a_missing_referenced_file(self):
        directory = self.skill(
            "name: demo-skill\ndescription: " + LONG_DESCRIPTION,
            body="See [the guide](references/missing.md).\n",
        )
        errors = vs.validate_skill(directory)
        self.assertTrue(any("referenced file does not exist" in e for e in errors), errors)

    def test_accepts_a_block_scalar_description(self):
        frontmatter = (
            "name: demo-skill\ndescription: >\n"
            "  Extracts text and tables from PDF files and fills forms.\n"
            "  Use when the user mentions PDFs."
        )
        directory = self.skill(frontmatter)
        self.assertEqual(vs.validate_skill(directory), [])

    def test_accepts_a_metadata_map(self):
        frontmatter = (
            "name: demo-skill\ndescription: %s\nmetadata:\n  version: \"1.0\"\n" % LONG_DESCRIPTION
        )
        directory = self.skill(frontmatter)
        self.assertEqual(vs.validate_skill(directory), [])

    def test_rejects_empty_metadata(self):
        frontmatter = "name: demo-skill\ndescription: %s\nmetadata:\n" % LONG_DESCRIPTION
        directory = self.skill(frontmatter)
        errors = vs.validate_skill(directory)
        self.assertTrue(any("metadata must be a mapping" in e for e in errors), errors)

    def test_rejects_a_body_over_the_budget(self):
        directory = self.skill(
            "name: demo-skill\ndescription: " + LONG_DESCRIPTION,
            body="\n".join("line %d" % n for n in range(501)),
        )
        errors = vs.validate_skill(directory)
        self.assertTrue(any("keep it under" in e for e in errors), errors)

    def test_rejects_a_file_without_frontmatter(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name) / "demo-skill"
        directory.mkdir()
        (directory / "SKILL.md").write_text("# No frontmatter\n")
        errors = vs.validate_skill(directory)
        self.assertTrue(any("does not start with YAML frontmatter" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
