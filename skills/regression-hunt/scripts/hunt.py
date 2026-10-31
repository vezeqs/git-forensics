#!/usr/bin/env python3
"""Find the commit that introduced a regression, without touching the user's checkout.

The bisect runs inside a throwaway worktree created with `git worktree add
--detach`. The user's working tree, index, and current branch are never read or
written. The worktree is removed on exit unless --keep is passed.

Exit codes:
    0  first bad commit found
    2  bisect ran but reached no verdict (all good, all bad, or all skipped)
    3  interrupted
    4  usage or preflight failure
    1  unexpected error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA = "git-forensics/regression-hunt/v1"
SKIP = 125
EXIT_FOUND = 0
EXIT_ERROR = 1
EXIT_NO_VERDICT = 2
EXIT_INTERRUPTED = 3
EXIT_USAGE = 4

WRAPPER_SOURCE = '''\
import subprocess
import sys

try:
    result = subprocess.run({command!r}, shell=True, timeout={timeout!r})
    code = result.returncode
except subprocess.TimeoutExpired:
    code = {skip}
except OSError:
    code = {skip}

# The worktree is disposable. Restore tracked files so a build step or a
# formatter that writes into the tree cannot block the next checkout.
subprocess.run(
    ["git", "checkout", "--", "."],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

# 126 and 127 mean the command itself is unusable at this commit. A negative
# code means the probe was killed by a signal. Neither is evidence that the
# commit is good or bad, so both become a skip.
if code < 0 or code in (126, 127):
    code = {skip}
sys.exit(code)
'''


class GitError(RuntimeError):
    """A git command failed when it had to succeed."""


def run(args, cwd, timeout=None, check=True):
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise GitError("git is not installed or not on PATH")
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise GitError("%s failed (exit %d): %s" % (" ".join(args), proc.returncode, detail))
    return proc


def git(repo, *args, **kwargs):
    return run(["git", *args], cwd=repo, **kwargs)


def out(repo, *args):
    return git(repo, *args).stdout.strip()


def discover_repo(start):
    proc = git(start, "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        raise GitError("not inside a git repository: %s" % start)
    return Path(proc.stdout.strip())


def resolve_commit(repo, rev):
    proc = git(repo, "rev-parse", "--verify", "--quiet", rev + "^{commit}", check=False)
    if proc.returncode != 0:
        raise GitError("unknown revision: %s" % rev)
    return proc.stdout.strip()


class Worktree:
    """A detached worktree in the system temp directory."""

    def __init__(self, repo, rev, keep=False):
        self.repo = repo
        self.rev = rev
        self.keep = keep
        self.path = Path(tempfile.mkdtemp(prefix="git-forensics-bisect-"))
        self.created = False

    def __enter__(self):
        try:
            git(self.repo, "worktree", "add", "--detach", "--quiet", str(self.path), self.rev)
        except GitError:
            shutil.rmtree(self.path, ignore_errors=True)
            raise
        self.created = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.keep:
            self.destroy()
        return False

    def destroy(self):
        if not self.created:
            return
        git(self.repo, "worktree", "remove", "--force", str(self.path), check=False)
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        git(self.repo, "worktree", "prune", check=False)
        self.created = False


def write_wrapper(directory, command, timeout):
    path = Path(directory) / "bisect-run.py"
    path.write_text(WRAPPER_SOURCE.format(command=command, timeout=timeout, skip=SKIP))
    return path


def run_wrapper(worktree, wrapper, timeout_seconds):
    """Run the wrapper once and return its exit code. Used for preflight only."""
    budget = None if timeout_seconds is None else timeout_seconds + 30
    proc = run([sys.executable, str(wrapper)], cwd=worktree, timeout=budget, check=False)
    return proc.returncode


def preflight(worktree, wrapper, good, bad, timeout_seconds, force):
    """Prove the command actually distinguishes the two endpoints.

    Returns a list of warning strings. Raises GitError when the bisect cannot
    produce a meaningful answer and --force was not given.
    """
    warnings = []

    git(worktree.path, "checkout", "--detach", "--quiet", bad)
    code_at_bad = run_wrapper(worktree.path, wrapper, timeout_seconds)
    if code_at_bad == 0:
        if force:
            warnings.append(
                "the command succeeds at --bad; the verdict below is not evidence of a regression"
            )
        else:
            raise GitError(
                "the command succeeds at --bad (%s). There is no failure to bisect. "
                "Check that --cmd exits non-zero when the regression is present, "
                "or pass --force to run anyway." % bad[:12]
            )
    if code_at_bad == SKIP:
        warnings.append("the command was skipped at --bad; every probe may be a skip")

    git(worktree.path, "checkout", "--detach", "--quiet", good)
    code_at_good = run_wrapper(worktree.path, wrapper, timeout_seconds)
    if code_at_good != 0 and code_at_good != SKIP:
        if force:
            warnings.append(
                "the command fails at --good; the verdict below is not evidence of a regression"
            )
        else:
            raise GitError(
                "the command fails at --good (%s) with exit %d. Bisecting a command "
                "that already fails at the good endpoint gives a meaningless answer. "
                "Pass --force to run anyway." % (good[:12], code_at_good)
            )
    if code_at_good == SKIP:
        warnings.append("the command was skipped at --good; the endpoints are not comparable")

    return warnings


FIRST_BAD_PATTERNS = (
    # Git has printed both `is the first bad commit` and, in newer releases,
    # `is the first 'bad' commit`. Accept either, and either bisect term.
    re.compile(
        r"^([0-9a-f]{7,64}) is the first ['\"]?(?:bad|new)['\"]? commit", re.MULTILINE
    ),
    re.compile(
        r"^first ['\"]?(?:bad|new)['\"]? commit: \[([0-9a-f]{7,64})\]", re.MULTILINE
    ),
    re.compile(
        r"^# first ['\"]?(?:bad|new)['\"]? commit: \[([0-9a-f]{7,64})\]", re.MULTILINE
    ),
)


def parse_first_bad(text):
    for pattern in FIRST_BAD_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def parse_bisect_log(text):
    """Turn `git bisect log` into a list of steps.

    The log opens with one `# bad:` and one `# good:` line naming the endpoints,
    before the `git bisect start` line. Those are the range, not probes, so they
    are marked `endpoint` and kept out of the probe count.
    """
    steps = []
    started = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("git bisect start"):
            started = True
            continue
        match = re.match(
            r"^# ['\"]?(good|bad|skip|old|new)['\"]?: \[([0-9a-f]{7,64})\] (.*)$", line
        )
        if match:
            steps.append(
                {
                    "result": match.group(1),
                    "sha": match.group(2),
                    "subject": match.group(3),
                    "endpoint": not started,
                }
            )
    return steps


def parse_numstat(text):
    """Parse `git show --numstat -z` output into file records.

    With -z, paths are raw rather than quoted by core.quotePath, and records are
    NUL-terminated. A rename is emitted as `added<TAB>removed<TAB>NULoldNULnewNUL`.
    """
    records = text.split("\0")
    files = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record.strip():
            continue
        parts = record.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = (part.strip() for part in parts)
        if path == "" and index + 1 < len(records):
            old = records[index]
            new = records[index + 1]
            index += 2
            path = "%s => %s" % (old, new)
        files.append(
            {
                "path": path,
                "added": None if added == "-" else int(added),
                "removed": None if removed == "-" else int(removed),
            }
        )
    return files


def commit_details(repo, sha):
    fmt = "%H%x00%an%x00%ae%x00%aI%x00%s"
    raw = out(repo, "show", "-s", "--format=" + fmt, sha)
    sha_full, author, email, date, subject = raw.split("\0", 4)

    numstat = git(repo, "show", "--numstat", "-z", "--format=", sha, check=False).stdout
    files = parse_numstat(numstat)

    body = git(repo, "show", "-s", "--format=%b", sha, check=False).stdout.strip()

    return {
        "sha": sha_full,
        "short_sha": sha_full[:12],
        "subject": subject,
        "author": author,
        "email": email,
        "date": date,
        "body": body,
        "files_changed": files,
        "parents": out(repo, "rev-list", "--parents", "-n", "1", sha).split()[1:],
    }


def bisect(repo, good, bad, command, timeout_seconds, keep, force, no_preflight):
    warnings = []
    wrapper_dir = tempfile.mkdtemp(prefix="git-forensics-run-")
    wrapper = write_wrapper(wrapper_dir, command, timeout_seconds)
    started = time.time()

    try:
        with Worktree(repo, bad, keep=keep) as worktree:
            if keep:
                print("worktree: %s" % worktree.path, file=sys.stderr)
            if not no_preflight:
                warnings.extend(preflight(worktree, wrapper, good, bad, timeout_seconds, force))

            start = git(
                worktree.path, "bisect", "start", bad, good, check=False
            )
            if start.returncode != 0:
                raise GitError("git bisect start failed: %s" % (start.stderr or start.stdout).strip())

            run_proc = git(
                worktree.path,
                "bisect",
                "run",
                sys.executable,
                str(wrapper),
                check=False,
            )
            log_text = git(worktree.path, "bisect", "log", check=False).stdout
            git(worktree.path, "bisect", "reset", check=False)

            combined = (run_proc.stdout or "") + (run_proc.stderr or "")
            # `git bisect log` is the authoritative record of the verdict; the
            # console output is the fallback.
            first_bad = parse_first_bad(log_text) or parse_first_bad(combined)
            steps = parse_bisect_log(log_text)

            report = {
                "schema": SCHEMA,
                "good": resolve_commit(repo, good),
                "bad": resolve_commit(repo, bad),
                "command": command,
                "first_bad": commit_details(repo, first_bad) if first_bad else None,
                "steps": steps,
                "probes": sum(1 for step in steps if not step["endpoint"]),
                "warnings": warnings,
                "duration_seconds": round(time.time() - started, 2),
                "worktree": str(worktree.path) if keep else None,
                "raw_output": combined.strip().splitlines()[-40:],
            }
    finally:
        shutil.rmtree(wrapper_dir, ignore_errors=True)

    return report


def render_markdown(report):
    lines = ["# Regression hunt", ""]
    good = report["good"]
    bad = report["bad"]
    lines.append("- Good: `%s`" % good[:12])
    lines.append("- Bad: `%s`" % bad[:12])
    lines.append("- Command: `%s`" % report["command"])
    lines.append("- Probes: %d" % report["probes"])
    lines.append("- Duration: %ss" % report["duration_seconds"])
    lines.append("")

    for warning in report["warnings"]:
        lines.append("> Warning: %s" % warning)
    if report["warnings"]:
        lines.append("")

    commit = report["first_bad"]
    if commit is None:
        lines.append("## Result")
        lines.append("")
        lines.append("No first bad commit. Every probe was skipped, or the range does not")
        lines.append("contain a failing commit. The raw output is below.")
        lines.append("")
        lines.append("```")
        lines.extend(report["raw_output"])
        lines.append("```")
        return "\n".join(lines)

    lines.append("## First bad commit")
    lines.append("")
    lines.append("`%s` %s" % (commit["short_sha"], commit["subject"]))
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append("| Author | %s <%s> |" % (commit["author"], commit["email"]))
    lines.append("| Date | %s |" % commit["date"])
    lines.append("| Parents | %s |" % (", ".join(p[:12] for p in commit["parents"]) or "none (root commit)"))
    lines.append("")

    if commit["files_changed"]:
        lines.append("### Files changed")
        lines.append("")
        lines.append("| File | + | - |")
        lines.append("| --- | --- | --- |")
        for entry in commit["files_changed"][:25]:
            added = "-" if entry["added"] is None else entry["added"]
            removed = "-" if entry["removed"] is None else entry["removed"]
            lines.append("| `%s` | %s | %s |" % (entry["path"], added, removed))
        if len(commit["files_changed"]) > 25:
            lines.append("| ... | | |")
        lines.append("")

    if commit["body"]:
        lines.append("### Commit message")
        lines.append("")
        lines.append("```")
        lines.extend(commit["body"].splitlines()[:20])
        lines.append("```")
        lines.append("")

    probes = [step for step in report["steps"] if not step["endpoint"]]
    if probes:
        lines.append("### Probes")
        lines.append("")
        lines.append("| Result | Commit | Subject |")
        lines.append("| --- | --- | --- |")
        for step in probes:
            lines.append("| %s | `%s` | %s |" % (step["result"], step["sha"][:12], step["subject"]))
        lines.append("")

    if report["worktree"]:
        lines.append("Worktree kept at `%s`." % report["worktree"])

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="hunt.py",
        description="Bisect a regression in an isolated worktree. The current checkout is untouched.",
    )
    parser.add_argument("--good", required=True, help="last known good revision")
    parser.add_argument("--bad", default="HEAD", help="first known bad revision (default: HEAD)")
    parser.add_argument(
        "--cmd",
        required=True,
        help="shell command that exits 0 when the commit is healthy and non-zero when it is broken",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="seconds allowed per probe; a timeout is treated as a skip (default: 300)",
    )
    parser.add_argument("--repo", default=".", help="path inside the repository (default: .)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    parser.add_argument("--keep", action="store_true", help="keep the worktree for inspection")
    parser.add_argument("--force", action="store_true", help="run even if preflight finds a bad range")
    parser.add_argument("--no-preflight", action="store_true", help="skip the endpoint checks")
    args = parser.parse_args(argv)

    if not args.cmd.strip():
        print("error: --cmd is empty", file=sys.stderr)
        return EXIT_USAGE
    if args.timeout is not None and args.timeout <= 0:
        print("error: --timeout must be positive", file=sys.stderr)
        return EXIT_USAGE

    try:
        repo = discover_repo(args.repo)
        good = resolve_commit(repo, args.good)
        bad = resolve_commit(repo, args.bad)
    except GitError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE

    if good == bad:
        print("error: --good and --bad resolve to the same commit", file=sys.stderr)
        return EXIT_USAGE

    ancestor = git(repo, "merge-base", "--is-ancestor", good, bad, check=False)
    if ancestor.returncode == 1:
        print(
            "error: --good %s is not an ancestor of --bad %s" % (good[:12], bad[:12]),
            file=sys.stderr,
        )
        return EXIT_USAGE

    if out(repo, "rev-parse", "--is-shallow-repository") == "true":
        print(
            "warning: this is a shallow clone; the bisect range may be incomplete",
            file=sys.stderr,
        )

    try:
        report = bisect(
            repo,
            good,
            bad,
            args.cmd,
            args.timeout,
            args.keep,
            args.force,
            args.no_preflight,
        )
    except GitError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("interrupted; worktree removed", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as exc:  # noqa: BLE001 - top-level guard for a CLI
        if os.environ.get("GIT_FORENSICS_DEBUG"):
            raise
        print("error: unexpected failure: %s" % exc, file=sys.stderr)
        print("set GIT_FORENSICS_DEBUG=1 for a traceback", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report))

    return EXIT_FOUND if report["first_bad"] else EXIT_NO_VERDICT


if __name__ == "__main__":
    sys.exit(main())
