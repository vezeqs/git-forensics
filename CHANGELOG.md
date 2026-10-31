# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 — unreleased

First release: two skills, `regression-hunt` and `blame-archaeology`.

### Added

- `regression-hunt` bisects in a throwaway worktree and refuses a range whose
  endpoints do not distinguish the failure.
- `blame-archaeology` traces a line to its commit and pull request, separating
  git facts from inference and reporting gaps instead of guessing.
- `--json` reports with a versioned schema for both skills.
- `tools/validate_skills.py`, a spec validator, run in CI on Python 3.9, 3.11,
  and 3.13.
- `examples/demo.sh` and `tools/render_assets.py`, which generate every README
  image from a real run.
- `docs/`: a terminal recording, three captures, and an architecture diagram,
  all derived from that run.
- A test that fails when `docs/` is older than the demo output.

### Fixed in the 2026-10-30 audit

Found by running `crit-code` over this repository. Full findings in
[`docs/audit-2026-10-30.md`](docs/audit-2026-10-30.md).

- `files_changed[].path` returned git's quoted display form (`"caf\303\251.txt"`)
  for any non-ASCII filename, which is not a usable path. The report now reads
  `--numstat -z` and emits raw paths, with renames as `old => new`.
- `make assets` wrote the SVGs before importing Pillow for the GIF, so a missing
  dependency left `docs/` half-regenerated with a stale GIF. It now checks the
  dependency first, renders into a staging directory, and moves files into place
  only when every image succeeded.
- `--keep` did not report where the worktree was when the preflight refused,
  leaving it in a random temp directory.
- The README advertised a test count that had gone stale; it no longer states one.
- Pillow was an undeclared build dependency. `requirements-dev.txt` pins it.
- The skill-name test matched a substring anywhere in the file instead of parsing
  the frontmatter.

### Fixed during the pre-release audit

Bugs found by adversarial testing before the first release. Each has a
regression test.

- `regression-hunt --keep` removed the worktree anyway, because the context
  manager ignored the flag. Kept worktrees are now actually kept.
- A command that rewrote a tracked file (a build step, a formatter) made the
  next checkout fail with "Your local changes would be overwritten". Tracked
  files are now restored after every probe.
- A probe killed by a signal was reported to git as a failing commit. Negative
  exit codes now map to skip, like a timeout.
- `blame-archaeology` crashed with a `KeyError` when `gh` returned pull request
  data, because `--jq '.[]'` emits one object per line rather than an array.
- A `gh` timeout surfaced as a usage error (exit 4) instead of a reported gap.
- Blaming a directory produced a raw `[Errno 21] Is a directory` and exit 1.
  It is now a usage error with a clear message.
- Blaming an untracked file produced a raw `git blame` failure. It now says the
  file is not tracked.
- A line introduced while resolving a merge was attributed to the merge without
  saying so. The report now states that the commit is a merge and names its
  parents.
- `--force` overrode the preflight silently. The report now records that the
  verdict is not evidence of a regression.
- The validator misread YAML block scalars (`description: >`) as a short
  description, and had no negative tests. Both fixed.
- The verdict parser only matched `is the first bad commit`. Git 2.55 prints
  `is the first 'bad' commit`, so on those versions every bisect silently
  reported no verdict. Both forms parse now, the authoritative
  `git bisect log` line is read first, and the console wording is covered by
  unit tests.

### Fixed in the documentation

- The README claimed `git bisect` refuses a dirty checkout. It does not.
- The README quoted a scratch run whose hashes and probe count differed from
  the demo script.
- The submodule and merge-attribution limits were overstated.
- `regression-hunt/SKILL.md` referred to a `.git/forensics` directory that the
  implementation no longer uses.
