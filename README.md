# git-forensics

Two questions git does not answer directly. Two agent skills that do.

| Skill | Question | Guarantee |
| --- | --- | --- |
| `regression-hunt` | When did this break? | Bisects in a throwaway worktree. Your checkout is never touched. |
| `blame-archaeology` | Why does this line exist? | Traces the line to a commit, a pull request, and an issue, and labels what it could not find. |

Neither skill guesses. When the evidence runs out, they say so.

## The problem

Agents are good at reading code and bad at two specific things.

**Bisecting.** `git bisect` mutates the working tree, refuses to start on a
dirty checkout, and leaves the repository mid-bisect when a probe hangs or the
agent loses track. An agent that runs it in your checkout can destroy uncommitted
work, and often does.

**Explaining history.** Asked why a line exists, an agent will produce a
confident paragraph about intent that no commit supports. The commit subject says
"refactor"; the agent says "to fix a race condition". That is fabrication with a
straight face.

Both problems have the same shape: the correct method is mechanical and
tedious, and the failure mode is a plausible invention. So the method lives in a
script, and the invention is structurally prevented.

## Demo

A parser regresses between `v0.1.0` and `HEAD`. The agent runs one command:

```console
$ python3 skills/regression-hunt/scripts/hunt.py \
    --good v0.1.0 --bad HEAD \
    --cmd 'python3 -c "from src.parser import parse_duration; raise SystemExit(0 if parse_duration(\"1h 30m\") == 90 else 1)"'

# Regression hunt

- Good: `a9985f14044f`
- Bad: `eecc7b526edc`
- Probes: 3

## First bad commit

`fbfdd8287759` split durations on colons

| Field | Value |
| --- | --- |
| Author | Ada Lovelace <ada@example.com> |
| Date | 2026-10-30T22:45:57-05:00 |
| Parents | a9985f14044f |

### Files changed

| File | + | - |
| --- | --- | --- |
| `src/parser.py` | 1 | 1 |
```

The command is wrong? The tool tells you before it wastes ten minutes:

```console
$ python3 skills/regression-hunt/scripts/hunt.py --good v0.1.0 --bad HEAD --cmd "pytest -q"
error: the command fails at --good (a9985f14044f) with exit 1. Bisecting a
command that already fails at the good endpoint gives a meaningless answer.
Pass --force to run anyway.
```

The second skill answers the other question, and refuses to overreach:

```console
$ python3 skills/blame-archaeology/scripts/archaeology.py src/parser.py:4

## Fact: introduced by

`fbfdd8287759` split durations on colons

| Field | Value |
| --- | --- |
| Author | Ada Lovelace <ada@example.com> |
| Path at the time | `src/parser.py` |
| Line at the time | 4 |

## Gaps

- origin is not a GitHub remote, so the pull request lookup was skipped
```

On a repository with a GitHub remote and `gh` installed, the report adds the
pull request that GitHub associates with the commit, under an `Inference`
heading, with the caveat spelled out. When that lookup is unavailable, the
reason appears under `Gaps` instead of a guess.

Every section is either `Fact` (read from git) or `Inference` (an association
that may be wrong). `Gaps` is not a failure state; it is the answer being honest.

## Reproduce this

The demo above is a script. It builds the repository, breaks the parser, and
runs both skills against it:

```sh
./examples/demo.sh
```

No network, no fixtures, nothing left behind.

## Install

Any client that discovers `skills/<name>/SKILL.md` works: Claude Code, Codex,
Cursor, Gemini CLI, Devin, OpenCode.

```sh
# copy one or both into your client's skills directory
cp -r skills/regression-hunt ~/.claude/skills/
cp -r skills/blame-archaeology ~/.devin/skills/
```

Or, if you use the skills CLI:

```sh
npx skills add vezeqs/git-forensics
```

Requirements: `git` 2.20 or newer and Python 3.9 or newer. No third-party
packages. `gh` is optional and only used for pull request lookups.

## How they stay safe

**`regression-hunt` never touches your checkout.** It runs
`git worktree add --detach` into a temp directory and bisects there. Your
branch, index, and uncommitted changes are not read. The worktree is removed on
exit, on error, and on Ctrl-C. `--keep` leaves it for inspection.

**It refuses a range that cannot answer the question.** Before bisecting, it
runs your command at both endpoints. If the command passes at `--bad`, there is
no failure to find. If it fails at `--good`, the answer would be meaningless.
Both cases stop with exit 4 instead of producing a confident wrong commit.

**Timeouts are skips, not verdicts.** A probe that exceeds `--timeout` is
reported to git as skip (125), the same as an untestable commit. It never gets
counted as "good" or "bad".

**`blame-archaeology` only reads.** It runs `git blame`, `git show`, `git log`,
and one `GET` through `gh api`. It has no write path.

## Exit codes

Both scripts use the same convention, so a caller can branch on them.

| Code | `regression-hunt` | `blame-archaeology` |
| --- | --- | --- |
| 0 | First bad commit found | History found |
| 1 | Unexpected failure | Unexpected failure |
| 2 | No verdict | Line is uncommitted |
| 3 | Interrupted | — |
| 4 | Usage or preflight failure | Bad path, bad line, or not a repository |

`--json` prints a versioned schema. See
[regression-hunt/references/report-format.md](skills/regression-hunt/references/report-format.md)
and
[blame-archaeology/references/report-format.md](skills/blame-archaeology/references/report-format.md).

## What is not covered

- **Flaky tests.** Bisect assumes a stable answer per commit. A flaky command
  produces a confident, wrong commit. Quarantine the test first.
- **Shallow clones.** The range may be incomplete. The tool warns, but cannot
  repair it.
- **Submodules.** They are not initialized in the worktree, so a command that
  needs them fails everywhere and reads as "bad" at every commit.
- **Squashed history.** If the repository was imported as one commit, there is
  no archaeology to do. The skill reports a gap rather than reconstructing a
  plausible past.
- **Merge attribution.** A line that arrived through a merge is blamed on the
  merge commit's parents, not on the person who clicked merge. The report names
  the parents.

## Development

```sh
make check     # validator + 34 tests
make test      # tests only
make validate  # SKILL.md conformance only
```

The suite creates real repositories in a temp directory and drives the scripts
as subprocesses. It does not touch the network; the GitHub payload parser is
tested against fixtures.

Layout:

```
skills/<name>/SKILL.md        instructions the agent reads
skills/<name>/scripts/*.py    the mechanical part
skills/<name>/references/     loaded only when needed
tools/validate_skills.py      spec conformance for this repo
tests/                        behavioural tests
```

## License

MIT.
