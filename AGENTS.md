# AGENTS.md

Operating instructions for agents working in this repository. Read this before
changing a skill.

## What this repository is

Two agent skills that answer two questions about a git repository, plus the
machinery that keeps the answers honest: tests that build real repositories, a
validator that enforces the skill spec, and a renderer that produces the README
images from a real run.

The skills are the product. Everything else exists so a reader can verify the
claims instead of trusting them.

## Which skill answers which question

| The user asks | Skill | Command |
| --- | --- | --- |
| "When did this break?", "which commit broke it", "bisect this" | `regression-hunt` | `python3 scripts/hunt.py --good <rev> --bad <rev> --cmd "<test>"` |
| "Why is this line here?", "who wrote this and why", "when did this behavior appear" | `blame-archaeology` | `python3 scripts/archaeology.py path:line` |

If the user wants a cause and you only have a commit, read the diff before
answering. Neither skill claims to explain intent.

## Invariants

These are not preferences. A change that breaks one is wrong even if the tests
pass, so fix the tests too.

1. **`regression-hunt` never writes to the user's checkout.** The only writes it
   performs are `git worktree add/remove/prune` for a temp directory it created,
   and the wrapper file in a temp directory.
2. **`blame-archaeology` has no write path.** `git blame`, `git show`,
   `git log`, and one `GET` through `gh api`. Nothing else.
3. **No claim without evidence.** Output is tagged `Fact` (read from git) or
   `Inference` (an association that may be wrong). Missing evidence goes in
   `Gaps`. Never fill a gap with a plausible story.
4. **Exit codes are a contract.** 0 found, 2 no verdict, 3 interrupted,
   4 usage, 1 unexpected. Do not renumber. The README table and the tests both
   depend on it.
5. **No third-party runtime dependency.** The skills run on the standard library
   and Python 3.9+. Pillow is allowed only in `tools/render_assets.py`, which is
   never installed by a user.
6. **A timeout, a signal, or exit 126/127 is a skip.** Never a verdict. Git's
   skip code is 125 and the wrapper is the only place that maps them.
7. **Skills are self-contained.** No imports across `skills/*/scripts/`. A user
   may install one skill and not the other. Small duplication is correct.

## Layout

| Path | What lives there |
| --- | --- |
| `skills/<name>/SKILL.md` | Instructions the agent reads. The product. |
| `skills/<name>/scripts/*.py` | The mechanical part. Standard library only. |
| `skills/<name>/references/` | Detail loaded only when a task needs it. |
| `tools/validate_skills.py` | Spec conformance for this repository. |
| `tools/render_assets.py` | Generates `docs/` from `examples/demo.sh`. |
| `tests/` | Behavioural tests. They create real repositories. |
| `examples/demo.sh` | Builds a broken repository and runs both skills. |
| `docs/` | Generated images. Do not edit by hand. |

## Commands

```sh
make validate   # SKILL.md conformance
make test       # behavioural tests
make check      # both, and what CI runs
make assets     # regenerate docs/ from a real demo run
```

## Changing a skill

1. Write the failing test first. The suite is the specification.
2. Change the script.
3. Run `make check`.
4. If the output shape changed, update `skills/<name>/references/report-format.md`
   in the same commit.
5. If the demo output changed, run `make assets` and commit `docs/` with it.
6. Quote real output in the README. Never type an example by hand.

## Adding a skill

1. `skills/<name>/SKILL.md`, with `name` equal to the directory name.
2. Scripts in `skills/<name>/scripts/`, standard library only.
3. Tests under `tests/` that drive the script as a subprocess against a real
   repository created in a temp directory.
4. `make check`.
5. Add it to the question table at the top of the README and to the table in
   this file.

## Review checklist

- [ ] New behaviour has a test that failed before the change.
- [ ] No new runtime dependency.
- [ ] `SKILL.md` under 500 lines, frontmatter valid, description names the words
      a user would actually use.
- [ ] Exit codes unchanged, or the table and tests changed with them.
- [ ] `references/report-format.md` matches the JSON the script emits.
- [ ] `docs/` regenerated if the demo output changed.
- [ ] No write outside a temp directory.
- [ ] Nothing in the diff claims a cause that no commit, PR, or issue states.

## Sharp edges

Things that have already caused bugs here. Read before editing.

- **`git bisect start` does not refuse a dirty tree.** It will happily run if
  the dirty files are not touched by the commits in range. Do not write code or
  docs that assume otherwise.
- **A probe can dirty the worktree.** A build or formatter that writes tracked
  files makes the *next* checkout fail. The wrapper restores tracked files after
  every probe for this reason. Untracked files that collide with a commit in
  range are still a limitation.
- **`gh api .../commits/<sha>/pulls` returns a JSON array.** `--jq '.[] | {...}'`
  emits one object per line and breaks a `json.loads` of the whole output. Parse
  the array.
- **`git bisect` wording changes between releases.** Older git prints
  `is the first bad commit`; 2.55 prints `is the first 'bad' commit`. Parse the
  `git bisect log` line first, keep the console patterns tolerant, and keep
  unit tests for both forms. This exact difference made every CI run report no
  verdict while local runs passed.
- **`git show --numstat` on a merge commit prints nothing** without `-m`. An
  empty `files_changed` for a merge is expected, not a bug.
- **`git blame` on a merge** attributes a conflict-resolution line to the merge
  commit. The report must say so and name the parents.
- **Commit dates in `examples/demo.sh` are fixed** so the hashes in the README
  are stable. Changing the demo's content changes every hash in the README.
- **ImageMagick renders SVG differently from a browser.** Validate the XML, and
  avoid `<tspan>` and markers if the element must survive both.

## Definition of done

- [ ] `make check` passes.
- [ ] `make assets` produces no unintended diff.
- [ ] The README quotes only output you can reproduce.
- [ ] No secrets, no generated artifacts outside `docs/`, no `__pycache__`.

## Working in this repository

- Do not reformat files you were not asked to touch.
- Do not change the license. MIT; keep the copyright notice.
- Do not hand-edit `docs/`; regenerate it.
- If a check fails, fix the cause. Do not loosen the validator to pass.
