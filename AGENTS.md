# AGENTS.md

Operating instructions for agents working in this repository. Read this before
changing a skill.

## What this repository is

Two agent skills for git forensics, plus the tests and the validator that keep
them honest. It is a small repository on purpose: two skills that work beat
twenty that half-work.

## Layout

| Path | What lives there |
| --- | --- |
| `skills/<name>/SKILL.md` | Instructions the agent reads. The product. |
| `skills/<name>/scripts/*.py` | The mechanical part. No third-party imports. |
| `skills/<name>/references/` | Detail loaded only when a task needs it. |
| `tools/validate_skills.py` | Spec conformance for this repository. |
| `tests/` | Behavioural tests. They create real repositories. |
| `examples/demo.sh` | Builds a broken repository and runs both skills. Kept working by a test. |

## House rules

- Python 3.9 or newer, standard library only. A skill that needs `pip install`
  is a skill half the users cannot run.
- Skills are self-contained. Do not import code across skill directories; a
  user may install one skill without the other. Small duplication is correct
  here.
- `SKILL.md` stays under 500 lines. Move detail to `references/` and link it.
- The frontmatter `name` must equal the directory name, lowercase, single
  hyphens. `make validate` enforces this.
- Descriptions are routing metadata, not marketing. Say what the skill does and
  the words a user would use to ask for it.
- Exit codes are a contract. Do not renumber them; see the table in the README.

## What these skills must never do

- Write to the user's checkout. `regression-hunt` bisects in a worktree;
  `blame-archaeology` only reads.
- Rewrite history, rebase, or clean up refs.
- State a cause it did not read. Facts and inferences stay labelled.
- Hide a failure behind a default. If the evidence is missing, report a gap.

## Verification

Run all three before reporting work as done:

```sh
make validate   # SKILL.md conformance
make test       # behavioural tests
make check      # both
```

The suite is the specification. If you change behaviour, change the test in the
same commit, and make the test fail first.

## Adding a skill

1. Create `skills/<name>/SKILL.md` with `name` equal to the directory name.
2. Put any script in `skills/<name>/scripts/`, standard library only.
3. Add tests under `tests/` that drive the script as a subprocess.
4. Run `make check`.
5. Add the skill to the table at the top of the README.

## Common mistakes

- Editing a script without running `make test`.
- Adding a dependency that is not in the standard library.
- Growing `SKILL.md` past 500 lines instead of moving detail to `references/`.
- Making a skill depend on another skill's script.
- Reporting a bisect result without the command that produced it.
- Treating a timeout or a skip as evidence.

## Definition of done

- [ ] `make check` passes.
- [ ] New behaviour has a test that failed before the change.
- [ ] No new dependency.
- [ ] `SKILL.md` still under 500 lines, frontmatter valid.
- [ ] README table updated if a skill was added.
- [ ] Nothing in the diff writes to a user's repository outside a worktree.

## Working in this repository

- Do not reformat files you were not asked to touch.
- Do not change the license. MIT; keep the copyright notice.
- Do not commit `__pycache__` or test artifacts.
- If a check fails, fix the cause. Do not loosen the validator to pass.
