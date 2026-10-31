---
name: blame-archaeology
description: Trace why a specific line of code exists by blaming it to a commit, following renames, showing the surrounding change, and finding the pull request and issues that motivated it, with git facts and inferences kept separate. Use when the user asks why a line exists, who wrote it and why, when a behavior was introduced, what change caused a piece of code, or asks for the history behind a specific line.
license: MIT
metadata:
  version: "1.0.0"
  author: vezeqs
---

# Blame archaeology

Answer one question honestly: **why does this line exist?**

The hard part is not running `git blame`. It is not inventing a story when the
history is thin. This skill produces an evidence trail and labels every claim as
either a git fact or an inference.

## When to use

- "Why is this here?", "who wrote this and why?", "when did this behavior
  appear?", "what change introduced this check?"
- Before deleting or changing code whose purpose is not obvious.
- When a comment and the code disagree, and the user wants to know which is
  older.

Do not use it when:

- The user wants the commit that broke a test. Use `regression-hunt`.
- The line is generated, minified, or vendored. Blame on generated code
  attributes everything to the generator's commit and tells you nothing.
- The repository history was squashed at import. There is no archaeology to do;
  say so instead of reconstructing a plausible past.

## Run it

```sh
python3 scripts/archaeology.py src/parser.py:142
```

`--json` for machine output, `--no-pr` to skip the GitHub lookup, `--context N`
to widen the code excerpt (default 3 lines).

The script is read-only. It runs `git blame`, `git show`, `git log`, and a
single read-only `gh api` call when `origin` is a GitHub remote.

For the JSON schema and field meanings, read
[references/report-format.md](references/report-format.md).

## What it gives you

| Section | Status | Meaning |
| --- | --- | --- |
| Introduced by | fact | The commit that last touched the line, from `git blame`. |
| Path at the time | fact | Where the file lived then. Blame follows the content, not the name. |
| Rename trail | fact | Commits that renamed the path, newest first. |
| Pull request | inference | GitHub associates the commit with a PR. Association is not intent. |
| Linked issues | inference | Issue numbers found in the commit or PR text. A mention is not a cause. |
| Gaps | fact | What the tool could not establish, stated instead of filled in. |

## Exit codes

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | History found | Report the evidence. |
| 2 | The line is uncommitted | Say so. There is no history. |
| 4 | Bad path, bad line number, or not a repository | Fix the target. |

## Reporting the result

Structure the answer the same way the tool does: facts first, inference second,
gaps last.

```
The line is `if not user.is_active: return None` in src/auth.py:142.

Fact: introduced in 4f2a91c "reject inactive users before token issue"
(Ada Lovelace, 2025-03-11). The file was `src/session.py` then; it was renamed
in 9c01b7e.

Inference: PR #318 "Stop issuing tokens to deactivated accounts" describes the
same behavior, and closes #301. GitHub links the commit to #318; the link does
not prove the PR body is accurate.

Gap: no issue text was available for #301, so the original report is unknown.
```

Rules for the report:

- Quote the SHA, the subject, the author, and the date. Do not paraphrase a
  commit subject.
- Keep the `Fact:` and `Inference:` labels. They are the point of the skill.
- Never state a motive that is not written down. "The author wanted to fix a
  race" is a fabrication unless a commit, PR, or issue says so.
- When a gap exists, report the gap. An honest "the history does not say" is a
  better answer than a confident story.
- If blame lands on a merge commit, say that the line came in through a merge
  and name both parents. Do not attribute it to the merger.

## Rules

- Do not run `git log -S` or `-G` and present the result as the origin of a
  line. Pickaxe finds when a string changed count, which is a different
  question, and it is noisy across renames.
- Do not "clean up" history, rebase, or rewrite commits while investigating.
- Do not pass `--no-pr` to avoid a slow lookup and then speculate about the
  pull request. Report the gap instead.

## Limits

- `git blame` attributes the last change to a line, not the first. A
  reformatting commit will own lines whose meaning is older. If the blamed
  commit is a pure reformat, follow `previous` in the blame output and repeat.
- Rename detection is heuristic. A file that was copied and heavily edited may
  appear as a new file.
- Pull request lookup needs `gh` and a GitHub `origin`. Without either, the
  report says so and stops there.
