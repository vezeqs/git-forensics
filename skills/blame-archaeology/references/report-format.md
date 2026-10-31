# Report format

`archaeology.py --json` prints one object. Without `--json` the same data is
printed as markdown.

## Schema

```json
{
  "schema": "git-forensics/blame-archaeology/v1",
  "target": {"path": "src/b.txt", "line": 3, "content": "gamma"},
  "blame": {
    "sha": "79afad5246ca...",
    "original_line": 3,
    "final_line": 3,
    "author": "Test",
    "author_mail": "t@example.com",
    "author_time": 1761876288,
    "summary": "add the parser skeleton",
    "filename": "src/a.txt",
    "previous": null,
    "content": "gamma"
  },
  "commit": {
    "sha": "79afad5246ca...",
    "author": "Test",
    "email": "t@example.com",
    "date": "2026-10-30T22:44:48-05:00",
    "subject": "add the parser skeleton",
    "body": "",
    "parents": ["1f158f2042a4..."]
  },
  "context": [{"number": 2, "text": "beta", "is_target": false}],
  "renames": [{"sha": "c6fb2a41ba1f...", "date": "2026-10-30", "subject": "rename parser",
               "renames": [{"from": "src/a.txt", "to": "src/b.txt"}]}],
  "pull_request": {"number": 318, "title": "...", "url": "...", "mergedAt": "...",
                   "author": "ada", "body": "..."},
  "issues": {"explicit": [301], "mentioned": [288]},
  "gaps": ["origin is not a GitHub remote, so the pull request lookup was skipped"]
}
```

## Fields

| Field | Meaning |
| --- | --- |
| `target` | The requested line and its current content. |
| `blame.sha` | Commit that last touched the line. All zeros means uncommitted. |
| `blame.original_line` | Line number in the blamed blob. Differs from `target.line` after later edits. |
| `blame.filename` | Path at the blamed commit, before any rename. |
| `blame.previous` | `{sha, path}` when git recorded a previous location. Null otherwise. |
| `commit` | Metadata for `blame.sha`. Null when the line is uncommitted. |
| `commit.parents` | Full SHAs of the parents. More than one means a merge commit, which the markdown report calls out. |
| `context` | Lines around the target as they were at the blamed commit. |
| `renames` | Rename commits for the path, newest first. Empty when none. |
| `pull_request` | First PR GitHub associates with the commit. Null when absent. |
| `issues.explicit` | Numbers that followed a closing keyword (`fixes #12`). |
| `issues.mentioned` | Numbers that only appear as `#12` somewhere in the text. |
| `gaps` | What could not be established. Never empty by accident: if the PR lookup is skipped, the reason is here. |

## Exit codes

`0` history found, `2` uncommitted line, `4` usage failure, `1` unexpected error.

## Stability

`blame`, `commit`, `renames`, and `gaps` are the contract. `context` and
`pull_request.body` are for display and may change shape.
