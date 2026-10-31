#!/bin/sh
# Build a small repository, break it, and run both skills against it.
# Everything is created in a temp directory and removed on exit.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/git-forensics-demo.XXXXXX")
trap 'rm -rf "$WORK"' EXIT INT TERM

export GIT_AUTHOR_NAME="Ada Lovelace"
export GIT_AUTHOR_EMAIL="ada@example.com"
export GIT_COMMITTER_NAME="Ada Lovelace"
export GIT_COMMITTER_EMAIL="ada@example.com"
export GIT_AUTHOR_DATE="2026-03-02T09:00:00+00:00"
export GIT_COMMITTER_DATE="2026-03-02T09:00:00+00:00"
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null

cd "$WORK"
git init -q -b main
mkdir -p src tests

cat > src/parser.py <<'PY'
def parse_duration(text):
    """Parse "1h30m" into minutes."""
    total = 0
    for part in text.split():
        if part.endswith("h"):
            total += int(part[:-1]) * 60
        elif part.endswith("m"):
            total += int(part[:-1])
    return total
PY

git add . && git commit -qm "add a duration parser"
git tag v0.1.0

echo "# demo" > README.md && git add . && git commit -qm "add a readme"

sed 's/text.split()/text.split(":")/' src/parser.py > src/parser.py.new
mv src/parser.py.new src/parser.py
git commit -qam "split durations on colons"

echo "more" >> README.md && git commit -qam "expand the readme"

echo "Repository: $WORK"
git log --oneline | cat
echo

CHECK='python3 -c "from src.parser import parse_duration; raise SystemExit(0 if parse_duration(\"1h 30m\") == 90 else 1)"'

echo "== regression-hunt: which commit broke parse_duration? =="
echo
python3 "$ROOT/skills/regression-hunt/scripts/hunt.py" \
    --good v0.1.0 --bad HEAD --cmd "$CHECK"
echo

echo "== blame-archaeology: why does this line exist? =="
echo
python3 "$ROOT/skills/blame-archaeology/scripts/archaeology.py" src/parser.py:4
echo

echo "== regression-hunt: what happens with a command that is broken everywhere? =="
echo
python3 "$ROOT/skills/regression-hunt/scripts/hunt.py" \
    --good v0.1.0 --bad HEAD --cmd "python3 -m pytest -q" || true
