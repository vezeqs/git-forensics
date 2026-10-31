---
name: regression-hunt
description: Find the commit that introduced a regression by bisecting history in an isolated worktree. Use when a test, build, or behavior used to pass and now fails, when the user asks when something broke, which commit broke it, or asks to bisect. Requires a command that exits 0 on a healthy commit and non-zero on a broken one.
license: MIT
metadata:
  version: "1.0.0"
  author: vezeqs
---

# Regression hunt

Answer one question with evidence: **which commit introduced this failure?**

The bisect runs in a throwaway worktree. The user's working tree, index, and
branch are never touched, so an interrupted run cannot lose their work.

## When to use

- A test, build, typecheck, or runtime behavior used to pass and now fails.
- The user says "when did this break", "find the breaking commit", "bisect
  this", or "which change caused it".
- The failure is deterministic: the same command gives the same answer on the
  same commit.

Do not use it when:

- The failure is flaky. Bisect assumes a stable answer per commit; a flaky
  command produces a confident, wrong commit. Stabilize or quarantine the test
  first, then bisect.
- The command fails at every commit in the range. That is a broken environment,
  not a regression. The preflight will refuse; do not override it.
- The user wants to know *why* a line exists. Use `blame-archaeology`.

## Inputs you must establish

1. **A good revision.** A tag, branch, or SHA where the command passes.
2. **A bad revision.** Defaults to `HEAD`.
3. **A command.** Exit 0 means healthy, non-zero means broken.

If the user cannot name a good revision, help them find one from release tags,
CI history, or the last known working deployment. Do not guess a SHA and do not
pick one because it looks old. A wrong endpoint silently produces a wrong
answer.

If the user gives you a command that reports "all tests passed" style output,
make sure its exit code is meaningful. `pytest -q` is fine; `pytest -q | tail`
is not, because the pipeline's exit status is `tail`'s.

## Run it

```sh
python3 scripts/hunt.py \
  --good v1.4.0 \
  --bad HEAD \
  --cmd "pytest -q tests/test_parser.py"
```

Paths are relative to this skill's directory. Add `--repo /path/to/checkout`
when the working directory is elsewhere.

Useful flags:

| Flag | Use |
| --- | --- |
| `--timeout 900` | Slow builds. A timeout is treated as a skip, not as evidence. |
| `--json` | Machine-readable report, for pasting into an issue. |
| `--keep` | Keep the worktree so the user can inspect the failing state. |
| `--no-preflight` | Only when the user explicitly asks to skip the endpoint checks. |

For the JSON schema and exit-code contract, read
[references/report-format.md](references/report-format.md).

## Exit codes

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | First bad commit found | Report it with its evidence. |
| 2 | No verdict: every probe skipped, or nothing failed in the range | Say so plainly. Do not invent a culprit. |
| 3 | Interrupted | The worktree was removed. Nothing to clean up. |
| 4 | Usage or preflight failure | Read the message, fix the input, rerun. |

## Reporting the result

Lead with the commit, then the evidence, then the limit of the claim:

```
Regression introduced in 23ff297 "break the value" (Test, 2026-10-30).
The bisect ran 3 probes between v1.4.0 and HEAD; 23ff297 was the first
commit where `pytest -q tests/test_parser.py` failed.
Files changed: value.txt (+1 -1).
This identifies the change, not the cause. The diff is the next thing to read.
```

Rules for the report:

- Quote the full SHA and the subject verbatim.
- State the command and the endpoints. A bisect without its command is not
  reproducible.
- Say "this commit introduced the failure", not "this commit is the bug". A
  commit can expose a latent bug elsewhere.
- If exit code was 2, say the range contained no failing commit and stop.
- If the user asked why it broke, read the diff and the commit message before
  offering a mechanism. Do not infer a cause from the commit subject alone.

## Rules

- Never run `git bisect` directly in the user's checkout. That mutates their
  tree and leaves the repository in a bisecting state if it fails.
- Never pass `--force` to get past a preflight failure unless the user has
  explicitly asked to bisect a range you warned them about.
- Do not remove the worktree or prune worktrees by hand. The script removes
  what it created, including on error and on Ctrl-C.
- A probe may write into the worktree. Tracked files are restored after each
  run, so a build step is fine. Untracked files that collide with a commit in
  range can still block a checkout; if that happens, report it instead of
  forcing.
- Do not run this on a shallow clone without saying so. The range may be
  incomplete and the answer will look authoritative while being wrong.

## Limits

- Merge-heavy histories can produce a commit that is not on the first-parent
  path. Read the reported parents before blaming a person.
- Submodules are not initialized in the worktree. A command that needs them
  fails at both endpoints, so the preflight refuses the range. Initialize them
  inside a kept worktree if the user needs the answer.
- The worktree lives in the system temp directory. If `/tmp` is small and the
  build is large, point `TMPDIR` at a bigger volume.
