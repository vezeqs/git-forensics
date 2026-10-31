#!/usr/bin/env python3
"""Trace why a line exists: blame it, follow renames, read the change, find the PR.

Every statement in the output is tagged `fact` (read from git) or `inference`
(an association that may be wrong). Anything the tool could not establish is
listed under Gaps instead of being guessed. The script only reads: it runs
`git blame`, `git show`, `git log`, and a read-only `gh api` lookup.

Exit codes:
    0  history found and reported
    2  the line has no committed history (uncommitted or untracked)
    4  usage failure (bad path, bad line number, not a repository)
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
from pathlib import Path

SCHEMA = "git-forensics/blame-archaeology/v1"
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_HISTORY = 2
EXIT_USAGE = 4

NULL_SHA = re.compile(r"^0+$")
GITHUB_REMOTE = re.compile(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$")
ISSUE_REF = re.compile(r"(?:(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+)?#(\d+)")
CLOSING_KEYWORD = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE)


class UsageError(RuntimeError):
    """The request cannot be answered as asked."""


def run(args, cwd, check=True, timeout=None):
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
        raise UsageError("%s is not installed or not on PATH" % args[0])
    except subprocess.TimeoutExpired:
        raise UsageError("%s timed out" % " ".join(args))
    if check and proc.returncode != 0:
        raise UsageError("%s failed: %s" % (" ".join(args), (proc.stderr or proc.stdout).strip()))
    return proc


def git(repo, *args, **kwargs):
    return run(["git", *args], cwd=repo, **kwargs)


def out(repo, *args):
    return git(repo, *args).stdout.strip()


def discover_repo(start):
    proc = git(start, "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        raise UsageError("not inside a git repository: %s" % start)
    return Path(proc.stdout.strip())


def split_target(target, line_argument):
    if line_argument is not None:
        return target, line_argument
    if ":" not in target:
        raise UsageError("expected path:line, or a path plus --line")
    path, _, number = target.rpartition(":")
    if not number.isdigit():
        raise UsageError("expected path:line, got %r" % target)
    return path, int(number)


def parse_blame(text):
    """Parse `git blame --porcelain -L n,n` into a dict plus the blamed line."""
    lines = text.splitlines()
    if not lines:
        raise UsageError("git blame produced no output")
    header = lines[0].split()
    if len(header) < 3:
        raise UsageError("unexpected git blame output")
    data = {
        "sha": header[0],
        "original_line": int(header[1]),
        "final_line": int(header[2]),
        "author": None,
        "author_mail": None,
        "author_time": None,
        "summary": None,
        "filename": None,
        "previous": None,
    }
    content = None
    for line in lines[1:]:
        if line.startswith("\t"):
            content = line[1:]
            break
        key, _, value = line.partition(" ")
        if key == "author":
            data["author"] = value
        elif key == "author-mail":
            data["author_mail"] = value.strip("<>")
        elif key == "author-time":
            data["author_time"] = int(value)
        elif key == "summary":
            data["summary"] = value
        elif key == "filename":
            data["filename"] = value
        elif key == "previous":
            parts = value.split()
            if len(parts) == 2:
                data["previous"] = {"sha": parts[0], "path": parts[1]}
    data["content"] = content
    return data


def commit_metadata(repo, sha):
    fmt = "%H%x00%an%x00%ae%x00%aI%x00%s%x00%b"
    raw = out(repo, "show", "-s", "--format=" + fmt, sha)
    parts = raw.split("\0")
    while len(parts) < 6:
        parts.append("")
    return {
        "sha": parts[0],
        "author": parts[1],
        "email": parts[2],
        "date": parts[3],
        "subject": parts[4],
        "body": parts[5].strip(),
    }


def rename_trail(repo, path, limit=20):
    """Commits that renamed this path, newest first."""
    proc = git(
        repo,
        "log",
        "--follow",
        "--find-renames",
        "--name-status",
        "--format=%x00%H%x00%ad%x00%s",
        "--date=short",
        "--",
        path,
        check=False,
    )
    if proc.returncode != 0:
        return []
    trail = []
    current = None
    for raw in proc.stdout.splitlines():
        if raw.startswith("\0"):
            fields = raw.split("\0")
            if len(fields) >= 4:
                current = {"sha": fields[1], "date": fields[2], "subject": fields[3], "renames": []}
                trail.append(current)
            continue
        if raw.startswith("R") and current is not None:
            fields = raw.split("\t")
            if len(fields) == 3:
                current["renames"].append({"from": fields[1], "to": fields[2]})
    return [entry for entry in trail if entry["renames"]][:limit]


def line_context(repo, sha, path, line_number, radius):
    proc = git(repo, "show", "%s:%s" % (sha, path), check=False)
    if proc.returncode != 0:
        return None
    text = proc.stdout
    if "\0" in text:
        return None
    body = text.splitlines()
    start = max(1, line_number - radius)
    end = min(len(body), line_number + radius)
    rows = []
    for number in range(start, end + 1):
        rows.append(
            {
                "number": number,
                "text": body[number - 1],
                "is_target": number == line_number,
            }
        )
    return rows


def github_repo(repo):
    proc = git(repo, "remote", "get-url", "origin", check=False)
    if proc.returncode != 0:
        return None
    match = GITHUB_REMOTE.search(proc.stdout.strip())
    if not match:
        return None
    return "%s/%s" % (match.group(1), match.group(2))


def parse_pull_request_payload(text):
    """Map the JSON from `gh api .../commits/<sha>/pulls` to the report shape.

    Returns None when the payload is empty. Raises ValueError when the payload
    is not JSON, so the caller can report a gap instead of crashing.
    """
    try:
        payload = json.loads(text or "[]")
    except ValueError:
        raise ValueError("pull request lookup returned unparseable output")
    if not isinstance(payload, list):
        raise ValueError("pull request lookup returned an unexpected shape")
    if not payload:
        return None
    first = payload[0]
    if not isinstance(first, dict):
        raise ValueError("pull request lookup returned an unexpected shape")
    return {
        "number": first.get("number"),
        "title": first.get("title"),
        "url": first.get("html_url"),
        "mergedAt": first.get("merged_at"),
        "author": (first.get("user") or {}).get("login"),
        "body": first.get("body"),
    }


def pull_request(repo, sha, slug, gaps):
    if shutil.which("gh") is None:
        gaps.append("gh is not installed, so the pull request lookup was skipped")
        return None
    try:
        proc = run(
            ["gh", "api", "repos/%s/commits/%s/pulls" % (slug, sha)],
            cwd=repo,
            check=False,
            timeout=30,
        )
    except UsageError as exc:
        gaps.append("pull request lookup failed: %s" % exc)
        return None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        gaps.append("pull request lookup failed: %s" % (detail[0] if detail else "unknown error"))
        return None
    try:
        found = parse_pull_request_payload(proc.stdout)
    except ValueError as exc:
        gaps.append(str(exc))
        return None
    if found is None:
        gaps.append("no pull request on GitHub references this commit")
    return found


def issue_references(texts):
    explicit, mentioned = [], []
    for text in texts:
        if not text:
            continue
        for match in CLOSING_KEYWORD.finditer(text):
            number = int(match.group(1))
            if number not in explicit:
                explicit.append(number)
        for match in ISSUE_REF.finditer(text):
            number = int(match.group(1))
            if number not in mentioned:
                mentioned.append(number)
    mentioned = [n for n in mentioned if n not in explicit]
    return explicit, mentioned


def investigate(repo, path, line_number, radius, skip_pr):
    gaps = []
    absolute = (repo / path).resolve()
    if not absolute.exists():
        raise UsageError("no such file: %s" % path)

    total_lines = len(absolute.read_text(errors="replace").splitlines())
    if line_number < 1 or line_number > max(total_lines, 1):
        raise UsageError(
            "%s has %d lines; line %d is out of range" % (path, total_lines, line_number)
        )

    tracked = git(repo, "ls-files", "--error-unmatch", "--", path, check=False)
    if tracked.returncode != 0:
        raise UsageError("%s is not tracked by git; there is no history to trace" % path)

    proc = git(repo, "blame", "--porcelain", "-L", "%d,%d" % (line_number, line_number), "--", path, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise UsageError("git blame failed: %s" % detail)

    blame = parse_blame(proc.stdout)

    report = {
        "schema": SCHEMA,
        "target": {"path": path, "line": line_number, "content": blame["content"]},
        "blame": blame,
        "commit": None,
        "context": None,
        "renames": [],
        "pull_request": None,
        "issues": {"explicit": [], "mentioned": []},
        "gaps": gaps,
    }

    if NULL_SHA.match(blame["sha"]):
        gaps.append("the line is uncommitted; there is no history to trace")
        return report, EXIT_NO_HISTORY

    metadata = commit_metadata(repo, blame["sha"])
    report["commit"] = metadata

    blamed_path = blame["filename"] or path
    report["context"] = line_context(repo, blame["sha"], blamed_path, blame["original_line"], radius)
    report["renames"] = rename_trail(repo, path)

    slug = None if skip_pr else github_repo(repo)
    if skip_pr:
        gaps.append("pull request lookup disabled with --no-pr")
    elif slug is None:
        gaps.append("origin is not a GitHub remote, so the pull request lookup was skipped")
    else:
        pr = pull_request(repo, blame["sha"], slug, gaps)
        if pr:
            report["pull_request"] = pr

    texts = [metadata["body"], metadata["subject"]]
    if report["pull_request"]:
        texts.extend([report["pull_request"].get("body"), report["pull_request"].get("title")])
    explicit, mentioned = issue_references(texts)
    report["issues"] = {"explicit": explicit, "mentioned": mentioned}

    return report, EXIT_OK


def render_markdown(report):
    target = report["target"]
    lines = ["# Blame archaeology", ""]
    lines.append("`%s:%d`" % (target["path"], target["line"]))
    lines.append("")

    if report["context"]:
        lines.append("```")
        for row in report["context"]:
            marker = ">" if row["is_target"] else " "
            lines.append("%s %5d  %s" % (marker, row["number"], row["text"]))
        lines.append("```")
        lines.append("")

    commit = report["commit"]
    if commit is None:
        lines.append("## Result")
        lines.append("")
        lines.append("The line has no committed history.")
        for gap in report["gaps"]:
            lines.append("- %s" % gap)
        return "\n".join(lines)

    lines.append("## Fact: introduced by")
    lines.append("")
    lines.append("`%s` %s" % (commit["sha"][:12], commit["subject"]))
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append("| Author | %s <%s> |" % (commit["author"], commit["email"]))
    lines.append("| Date | %s |" % commit["date"])
    lines.append("| Path at the time | `%s` |" % (report["blame"]["filename"] or target["path"]))
    lines.append("| Line at the time | %d |" % report["blame"]["original_line"])
    lines.append("")

    if commit["body"]:
        lines.append("### Commit message")
        lines.append("")
        lines.append("```")
        lines.extend(commit["body"].splitlines()[:25])
        lines.append("```")
        lines.append("")

    if report["renames"]:
        lines.append("## Fact: rename trail")
        lines.append("")
        for entry in report["renames"]:
            for rename in entry["renames"]:
                lines.append(
                    "- `%s` -> `%s` in `%s` (%s) %s"
                    % (rename["from"], rename["to"], entry["sha"][:12], entry["date"], entry["subject"])
                )
        lines.append("")

    pr = report["pull_request"]
    if pr:
        lines.append("## Inference: pull request")
        lines.append("")
        lines.append("#%s %s" % (pr.get("number"), pr.get("title")))
        lines.append("")
        lines.append("- Author: %s" % pr.get("author"))
        lines.append("- Merged: %s" % pr.get("mergedAt"))
        lines.append("- URL: %s" % pr.get("url"))
        lines.append("")
        lines.append("GitHub associates the commit with this pull request. That is an")
        lines.append("association, not a statement of intent.")
        lines.append("")

    if report["issues"]["explicit"] or report["issues"]["mentioned"]:
        lines.append("## Inference: linked issues")
        lines.append("")
        for number in report["issues"]["explicit"]:
            lines.append("- #%d (closing keyword in the commit or pull request)" % number)
        for number in report["issues"]["mentioned"]:
            lines.append("- #%d (mentioned only)" % number)
        lines.append("")

    if report["gaps"]:
        lines.append("## Gaps")
        lines.append("")
        for gap in report["gaps"]:
            lines.append("- %s" % gap)
        lines.append("")

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="archaeology.py",
        description="Trace why a line exists, separating git facts from inference.",
    )
    parser.add_argument("target", help="path:line, for example src/app.py:42")
    parser.add_argument("--line", type=int, help="line number, if not given in the target")
    parser.add_argument("--repo", default=".", help="path inside the repository (default: .)")
    parser.add_argument("--context", type=int, default=3, help="context lines around the target (default: 3)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    parser.add_argument("--no-pr", action="store_true", help="skip the GitHub pull request lookup")
    args = parser.parse_args(argv)

    if args.context < 0:
        print("error: --context must not be negative", file=sys.stderr)
        return EXIT_USAGE

    try:
        repo = discover_repo(args.repo)
        path, line_number = split_target(args.target, args.line)
        report, code = investigate(repo, path, line_number, args.context, args.no_pr)
    except UsageError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
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

    return code


if __name__ == "__main__":
    sys.exit(main())
