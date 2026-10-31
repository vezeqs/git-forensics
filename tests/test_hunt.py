"""Behavioural tests for skills/regression-hunt/scripts/hunt.py."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import HUNT, commit, git, init_repo, run_script  # noqa: E402

sys.path.insert(0, str(HUNT.parent))
import hunt  # noqa: E402

HEALTHY = 'test "$(cat value.txt)" = good'


class RegressionHuntTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = init_repo(Path(self._tmp.name) / "repo")

        self.first_good = commit(self.repo, "add the value", {"value.txt": "good\n"})
        self.still_good = commit(self.repo, "add notes", {"notes.txt": "one\n"})
        self.breaking = commit(self.repo, "break the value", {"value.txt": "bad\n"})
        self.head = commit(self.repo, "more notes", {"notes.txt": "two\n"})

    def hunt(self, *args):
        return run_script(HUNT, list(args), self.repo)

    def test_finds_the_breaking_commit(self):
        code, stdout, stderr = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", HEALTHY
        )
        self.assertEqual(code, 0, stdout + stderr)
        self.assertIn(self.breaking[:12], stdout)
        self.assertIn("break the value", stdout)
        self.assertIn("## First bad commit", stdout)

    def test_reports_probes_from_the_bisect_log(self):
        code, stdout, _ = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", HEALTHY
        )
        self.assertEqual(code, 0)
        self.assertIn("### Probes", stdout)
        self.assertIn(self.head[:12], stdout)
        self.assertIn(self.first_good[:12], stdout)

    def test_json_report_has_the_documented_schema(self):
        code, stdout, stderr = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", HEALTHY, "--json"
        )
        self.assertEqual(code, 0, stdout + stderr)
        report = json.loads(stdout)
        self.assertEqual(report["schema"], "git-forensics/regression-hunt/v1")
        self.assertEqual(report["first_bad"]["sha"], self.breaking)
        self.assertEqual(report["first_bad"]["subject"], "break the value")
        self.assertEqual(report["good"], self.first_good)
        self.assertEqual(report["bad"], self.head)
        self.assertEqual(report["command"], HEALTHY)
        self.assertIsNone(report["worktree"])
        self.assertGreaterEqual(report["probes"], 1)
        self.assertEqual(
            [entry["path"] for entry in report["first_bad"]["files_changed"]], ["value.txt"]
        )

    def test_refuses_when_the_command_passes_at_bad(self):
        code, _, stderr = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", "true"
        )
        self.assertEqual(code, 4)
        self.assertIn("succeeds at --bad", stderr)

    def test_refuses_when_the_command_fails_at_good(self):
        code, _, stderr = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", "false"
        )
        self.assertEqual(code, 4)
        self.assertIn("fails at --good", stderr)

    def test_force_overrides_preflight(self):
        # With a command that passes everywhere, git marks every midpoint good
        # and reports the bad endpoint as the first bad commit. That answer is
        # meaningless, which is exactly why preflight refuses without --force.
        code, stdout, _ = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", "true", "--force"
        )
        self.assertEqual(code, 0)
        self.assertIn(self.head[:12], stdout)

    def test_rejects_a_good_revision_that_is_not_an_ancestor(self):
        code, _, stderr = self.hunt(
            "--good", self.head, "--bad", self.first_good, "--cmd", HEALTHY
        )
        self.assertEqual(code, 4)
        self.assertIn("is not an ancestor", stderr)

    def test_rejects_identical_endpoints(self):
        code, _, stderr = self.hunt(
            "--good", self.head, "--bad", self.head, "--cmd", HEALTHY
        )
        self.assertEqual(code, 4)
        self.assertIn("same commit", stderr)

    def test_rejects_an_unknown_revision(self):
        code, _, stderr = self.hunt(
            "--good", "does-not-exist", "--bad", self.head, "--cmd", HEALTHY
        )
        self.assertEqual(code, 4)
        self.assertIn("unknown revision", stderr)

    def test_timeouts_are_skips_not_verdicts(self):
        code, stdout, _ = self.hunt(
            "--good", self.first_good, "--bad", self.head,
            "--cmd", "sleep 5", "--timeout", "0.2", "--no-preflight",
        )
        self.assertEqual(code, 2)
        self.assertIn("No first bad commit", stdout)

    def test_leaves_no_worktree_behind(self):
        self.hunt("--good", self.first_good, "--bad", self.head, "--cmd", HEALTHY)
        listed = git(self.repo, "worktree", "list")
        self.assertEqual(len(listed.splitlines()), 1, listed)

    def test_keep_preserves_the_worktree(self):
        code, stdout, _ = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", HEALTHY, "--keep"
        )
        self.assertEqual(code, 0)
        listed = git(self.repo, "worktree", "list")
        self.assertEqual(len(listed.splitlines()), 2, listed)
        kept = [line for line in listed.splitlines() if "git-forensics-bisect-" in line]
        self.assertTrue(kept, listed)
        path = Path(kept[0].split()[0])
        self.addCleanup(lambda: git(self.repo, "worktree", "remove", "--force", str(path)))

    def test_does_not_touch_the_working_tree(self):
        (self.repo / "notes.txt").write_text("uncommitted edit\n")
        before = git(self.repo, "status", "--porcelain")
        code, stdout, stderr = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", HEALTHY
        )
        self.assertEqual(code, 0, stdout + stderr)
        self.assertEqual(git(self.repo, "status", "--porcelain"), before)
        self.assertEqual((self.repo / "notes.txt").read_text(), "uncommitted edit\n")
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")

    def test_survives_a_command_that_rewrites_a_tracked_file(self):
        # A build step or formatter that writes into the tree used to make the
        # next checkout fail with "Your local changes would be overwritten".
        code, stdout, stderr = self.hunt(
            "--good", self.first_good, "--bad", self.head,
            "--cmd", 'echo dirty > value.txt; test "$(git show HEAD:value.txt)" = "good"',
        )
        self.assertEqual(code, 0, stdout + stderr)
        self.assertIn(self.breaking[:12], stdout)

    def test_a_killed_probe_is_a_skip_not_a_verdict(self):
        code, stdout, _ = self.hunt(
            "--good", self.first_good, "--bad", self.head,
            "--cmd", "kill -9 $$", "--no-preflight",
        )
        self.assertEqual(code, 2)
        self.assertIn("No first bad commit", stdout)

    def test_force_records_that_the_verdict_is_not_evidence(self):
        code, stdout, _ = self.hunt(
            "--good", self.first_good, "--bad", self.head,
            "--cmd", "true", "--force", "--json",
        )
        self.assertEqual(code, 0)
        report = json.loads(stdout)
        self.assertTrue(
            any("not evidence of a regression" in w for w in report["warnings"]),
            report["warnings"],
        )

    def test_empty_command_is_rejected(self):
        code, _, stderr = self.hunt(
            "--good", self.first_good, "--bad", self.head, "--cmd", "   "
        )
        self.assertEqual(code, 4)
        self.assertIn("--cmd is empty", stderr)

    def test_outside_a_repository_is_rejected(self):
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        code, _, stderr = run_script(HUNT, ["--good", "a", "--bad", "b", "--cmd", "true"], outside)
        self.assertEqual(code, 4)
        self.assertIn("not inside a git repository", stderr)


class BisectOutputParsingTest(unittest.TestCase):
    """Git's console wording differs between releases. Both forms must parse."""

    SHA = "c881dd5361c79d97fd06fc1163c386d8b844c0db"

    def test_parses_the_unquoted_form(self):
        text = "%s is the first bad commit\n" % self.SHA
        self.assertEqual(hunt.parse_first_bad(text), self.SHA)

    def test_parses_the_quoted_form_that_newer_git_prints(self):
        text = "%s is the first 'bad' commit\n" % self.SHA
        self.assertEqual(hunt.parse_first_bad(text), self.SHA)

    def test_parses_the_bracketed_log_form(self):
        text = "# first bad commit: [%s] break the value\n" % self.SHA
        self.assertEqual(hunt.parse_first_bad(text), self.SHA)

    def test_ignores_lines_that_are_not_a_verdict(self):
        self.assertIsNone(hunt.parse_first_bad("running 'python3 bisect-run.py'\n"))

    def test_parses_probes_from_the_log(self):
        log = (
            "# bad: [aaa1111] four\n"
            "# good: [bbb2222] one\n"
            "# first bad commit: [aaa1111] four\n"
        )
        steps = hunt.parse_bisect_log(log)
        self.assertEqual([step["result"] for step in steps], ["bad", "good"])
        self.assertEqual(steps[0]["sha"], "aaa1111")
        self.assertEqual(steps[1]["subject"], "one")

    def test_parses_probes_when_git_quotes_the_terms(self):
        log = "# 'bad': [aaa1111] four\n# 'good': [bbb2222] one\n"
        steps = hunt.parse_bisect_log(log)
        self.assertEqual([step["result"] for step in steps], ["bad", "good"])


if __name__ == "__main__":
    unittest.main()
