"""Behavioural tests for skills/blame-archaeology/scripts/archaeology.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import ARCHAEOLOGY, ISOLATED_ENV, commit, git, init_repo, run_script  # noqa: E402

sys.path.insert(0, str(ARCHAEOLOGY.parent))
import archaeology  # noqa: E402


class BlameArchaeologyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = init_repo(Path(self._tmp.name) / "repo")

        self.origin = commit(
            self.repo, "add the parser skeleton", {"src/a.txt": "alpha\nbeta\ngamma\ndelta\n"}
        )
        git(self.repo, "mv", "src/a.txt", "src/b.txt")
        (self.repo / "src" / "b.txt").write_text("alpha\nbeta changed\ngamma\ndelta\n")
        git(self.repo, "add", "src/b.txt")
        git(self.repo, "commit", "-q", "-m", "rename the parser and fix beta")
        self.rename = git(self.repo, "rev-parse", "HEAD")
        self.head = commit(self.repo, "unrelated work", {"log.txt": "x\n"})

    def dig(self, *args):
        return run_script(ARCHAEOLOGY, [*args, "--no-pr"], self.repo)

    def test_traces_through_a_rename_to_the_original_commit(self):
        code, stdout, stderr = self.dig("src/b.txt:3")
        self.assertEqual(code, 0, stderr)
        self.assertIn(self.origin[:12], stdout)
        self.assertIn("add the parser skeleton", stdout)
        self.assertIn("`src/a.txt` -> `src/b.txt`", stdout)
        self.assertIn("Path at the time", stdout)

    def test_json_report_has_the_documented_schema(self):
        code, stdout, stderr = self.dig("src/b.txt:3", "--json")
        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["schema"], "git-forensics/blame-archaeology/v1")
        self.assertEqual(report["target"], {"path": "src/b.txt", "line": 3, "content": "gamma"})
        self.assertEqual(report["blame"]["sha"], self.origin)
        self.assertEqual(report["blame"]["filename"], "src/a.txt")
        self.assertEqual(report["commit"]["sha"], self.origin)
        self.assertEqual(report["commit"]["subject"], "add the parser skeleton")
        self.assertEqual(report["renames"][0]["renames"][0]["from"], "src/a.txt")
        self.assertIsNone(report["pull_request"])
        self.assertTrue(report["gaps"])

    def test_context_marks_the_target_line(self):
        code, stdout, _ = self.dig("src/b.txt:3", "--context", "1")
        self.assertEqual(code, 0)
        target_rows = [line for line in stdout.splitlines() if line.startswith(">")]
        self.assertEqual(len(target_rows), 1)
        self.assertIn("gamma", target_rows[0])

    def test_reports_an_uncommitted_line(self):
        with (self.repo / "src" / "b.txt").open("a") as handle:
            handle.write("uncommitted\n")
        self.addCleanup(lambda: (self.repo / "src" / "b.txt").write_text("alpha\nbeta changed\ngamma\ndelta\n"))
        code, stdout, _ = self.dig("src/b.txt:5")
        self.assertEqual(code, 2)
        self.assertIn("no committed history", stdout)
        self.assertIn("uncommitted", stdout)

    def test_rejects_a_directory(self):
        code, _, stderr = self.dig("src:1")
        self.assertEqual(code, 4)
        self.assertIn("is a directory", stderr)

    def test_rejects_an_untracked_file(self):
        (self.repo / "src" / "new.txt").write_text("one\ntwo\n")
        code, _, stderr = self.dig("src/new.txt:1")
        self.assertEqual(code, 4)
        self.assertIn("not tracked by git", stderr)

    def test_rejects_a_line_out_of_range(self):
        code, _, stderr = self.dig("src/b.txt:99")
        self.assertEqual(code, 4)
        self.assertIn("out of range", stderr)

    def test_rejects_a_missing_file(self):
        code, _, stderr = self.dig("src/missing.txt:1")
        self.assertEqual(code, 4)
        self.assertIn("no such file", stderr)

    def test_rejects_a_target_without_a_line_number(self):
        code, _, stderr = self.dig("src/b.txt")
        self.assertEqual(code, 4)
        self.assertIn("expected path:line", stderr)

    def test_line_flag_works_without_a_colon(self):
        code, stdout, stderr = self.dig("src/b.txt", "--line", "3")
        self.assertEqual(code, 0, stderr)
        self.assertIn("add the parser skeleton", stdout)

    def test_skips_the_pull_request_lookup_without_a_github_remote(self):
        code, stdout, _ = run_script(ARCHAEOLOGY, ["src/b.txt:3"], self.repo)
        self.assertEqual(code, 0)
        self.assertIn("## Gaps", stdout)
        self.assertIn("not a GitHub remote", stdout)


class PullRequestPayloadTest(unittest.TestCase):
    """The gh payload shape, tested without a network call."""

    def test_maps_the_first_pull_request(self):
        payload = json.dumps(
            [
                {
                    "number": 318,
                    "title": "Stop issuing tokens to deactivated accounts",
                    "html_url": "https://github.com/o/r/pull/318",
                    "merged_at": "2025-03-11T10:00:00Z",
                    "user": {"login": "ada"},
                    "body": "closes #301",
                }
            ]
        )
        result = archaeology.parse_pull_request_payload(payload)
        self.assertEqual(result["number"], 318)
        self.assertEqual(result["url"], "https://github.com/o/r/pull/318")
        self.assertEqual(result["mergedAt"], "2025-03-11T10:00:00Z")
        self.assertEqual(result["author"], "ada")

    def test_empty_payload_returns_none(self):
        self.assertIsNone(archaeology.parse_pull_request_payload("[]"))
        self.assertIsNone(archaeology.parse_pull_request_payload(""))

    def test_unparseable_payload_raises(self):
        with self.assertRaises(ValueError):
            archaeology.parse_pull_request_payload("not json")

    def test_unexpected_shape_raises(self):
        with self.assertRaises(ValueError):
            archaeology.parse_pull_request_payload('{"message": "Not Found"}')


    def test_flags_a_merge_commit_and_names_its_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "merge")
            commit(repo, "base", {"f.txt": "a\nb\nc\n"})
            git(repo, "checkout", "-q", "-b", "side")
            commit(repo, "side change", {"f.txt": "a\nside\nc\n"})
            git(repo, "checkout", "-q", "main")
            commit(repo, "main change", {"f.txt": "a\nmain\nc\n"})
            subprocess.run(
                ["git", "merge", "side", "-m", "merge side"],
                cwd=str(repo),
                capture_output=True,
                env=ISOLATED_ENV,
            )
            (repo / "f.txt").write_text("a\nresolved\nc\n")
            git(repo, "add", "f.txt")
            git(repo, "commit", "-q", "-m", "merge side")

            code, stdout, stderr = run_script(ARCHAEOLOGY, ["f.txt:2", "--no-pr"], repo)
            self.assertEqual(code, 0, stderr)
            self.assertIn("merge commit with 2 parents", stdout)

            code, stdout, _ = run_script(ARCHAEOLOGY, ["f.txt:2", "--no-pr", "--json"], repo)
            report = json.loads(stdout)
            self.assertEqual(len(report["commit"]["parents"]), 2)


if __name__ == "__main__":
    unittest.main()
