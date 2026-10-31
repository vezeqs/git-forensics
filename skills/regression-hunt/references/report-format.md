# Report format

`hunt.py --json` prints one object. `hunt.py` without `--json` prints the same
data as markdown.

## Schema

```json
{
  "schema": "git-forensics/regression-hunt/v1",
  "good": "619617e7579f4e4a2b1c0d9e8f7a6b5c4d3e2f10",
  "bad": "4b2ca3b45998a1b2c3d4e5f60718293a4b5c6d7e",
  "command": "pytest -q tests/test_parser.py",
  "first_bad": {
    "sha": "23ff297739d3...",
    "short_sha": "23ff297739d3",
    "subject": "break the value",
    "author": "Test",
    "email": "t@example.com",
    "date": "2026-10-30T22:44:34-05:00",
    "body": "",
    "files_changed": [{"path": "value.txt", "added": 1, "removed": 1}],
    "parents": ["619617e7579f..."]
  },
  "steps": [{"result": "bad", "sha": "4b2ca3b45998", "subject": "unrelated work"}],
  "probes": 3,
  "warnings": [],
  "duration_seconds": 0.1,
  "worktree": null,
  "raw_output": ["..."]
}
```

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `schema` | string | Version tag. Changes when a field is removed or renamed. |
| `good`, `bad` | string | Full SHAs, resolved from the arguments. |
| `command` | string | Exactly what was run, through `sh -c`, at every probe. |
| `first_bad` | object or null | Null when no verdict was reached. |
| `first_bad.files_changed` | array | `added` and `removed` are null for binary files. |
| `first_bad.parents` | array | Empty for a root commit. More than one entry means a merge. |
| `steps` | array | Parsed from `git bisect log`. `result` is `good`, `bad`, or `skip`. |
| `probes` | int | Length of `steps`. |
| `warnings` | array | Non-fatal problems: skipped endpoints, shallow clone. |
| `duration_seconds` | float | Wall clock for the whole run, including preflight. |
| `worktree` | string or null | Path when `--keep` was used, otherwise null. |
| `raw_output` | array | Last 40 lines of git's output. For debugging, not for reporting. |

## Exit codes

`0` found, `2` no verdict, `3` interrupted, `4` usage or preflight failure,
`1` unexpected error.

## Stability

`first_bad.sha`, `good`, `bad`, `command`, and `steps` are the contract.
`raw_output` and `duration_seconds` exist for humans and may change.
