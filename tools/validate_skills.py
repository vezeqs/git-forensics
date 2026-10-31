#!/usr/bin/env python3
"""Validate every SKILL.md in this repository against the Agent Skills spec.

Checks the required frontmatter, the naming rules, the context budget, and that
every relative file referenced from a skill body actually exists.

Usage: python3 tools/validate_skills.py [root]
Exit code 0 when every skill is valid, 1 when any check fails.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#][^)]*)\)")
BARE_PATH_RE = re.compile(r"`((?:scripts|references|assets)/[^`\s]+)`")

REQUIRED = ("name", "description")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_BODY_LINES = 500


def parse_frontmatter(text, path, errors):
    if not text.startswith("---\n"):
        errors.append("%s: file does not start with YAML frontmatter" % path)
        return {}, text
    end = text.find("\n---\n", 3)
    if end == -1:
        errors.append("%s: frontmatter is not closed with ---" % path)
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    data = {}
    key = None
    for number, line in enumerate(raw.splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  "):
            if key is None:
                errors.append("%s:%d: indented value without a parent key" % (path, number))
                continue
            data.setdefault(key + "__map", []).append(line.strip())
            continue
        if ":" not in line:
            errors.append("%s:%d: expected 'key: value'" % (path, number))
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) > 1:
            value = value[1:-1]
        data[key] = value
    return data, body


def validate_skill(skill_dir):
    errors = []
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        return ["%s: missing SKILL.md" % skill_dir]

    text = path.read_text(encoding="utf-8")
    data, body = parse_frontmatter(text, path, errors)

    for field in REQUIRED:
        if not data.get(field):
            errors.append("%s: missing required field %r" % (path, field))

    name = data.get("name", "")
    if name:
        if len(name) > MAX_NAME:
            errors.append("%s: name is %d characters, maximum is %d" % (path, len(name), MAX_NAME))
        if not NAME_RE.match(name):
            errors.append(
                "%s: name %r must be lowercase letters, digits, and single hyphens" % (path, name)
            )
        if name != skill_dir.name:
            errors.append(
                "%s: name %r does not match its directory %r" % (path, name, skill_dir.name)
            )

    description = data.get("description", "")
    if description and len(description) > MAX_DESCRIPTION:
        errors.append(
            "%s: description is %d characters, maximum is %d"
            % (path, len(description), MAX_DESCRIPTION)
        )
    if description and len(description) < 40:
        errors.append("%s: description is too short to route on (%d characters)" % (path, len(description)))

    compatibility = data.get("compatibility", "")
    if compatibility and len(compatibility) > MAX_COMPATIBILITY:
        errors.append("%s: compatibility exceeds %d characters" % (path, MAX_COMPATIBILITY))

    if "metadata" in data and "metadata__map" not in data:
        errors.append("%s: metadata must be a mapping of string keys to string values" % path)
    if "metadata__map" in data and "metadata" not in data:
        errors.append("%s: metadata values are indented under no key" % path)

    body_lines = body.splitlines()
    if not body.strip():
        errors.append("%s: body is empty" % path)
    if len(body_lines) > MAX_BODY_LINES:
        errors.append(
            "%s: body is %d lines, keep it under %d and move detail to references/"
            % (path, len(body_lines), MAX_BODY_LINES)
        )

    for target in sorted(set(LINK_RE.findall(body)) | set(BARE_PATH_RE.findall(body))):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (skill_dir / target).exists():
            errors.append("%s: referenced file does not exist: %s" % (path, target))

    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0] if argv else Path(__file__).resolve().parent.parent)
    skills_root = root / "skills"
    if not skills_root.is_dir():
        print("error: no skills/ directory under %s" % root, file=sys.stderr)
        return 1

    skill_dirs = sorted(p for p in skills_root.iterdir() if p.is_dir())
    if not skill_dirs:
        print("error: no skills found under %s" % skills_root, file=sys.stderr)
        return 1

    failures = 0
    for skill_dir in skill_dirs:
        errors = validate_skill(skill_dir)
        if errors:
            failures += 1
            for error in errors:
                print(error, file=sys.stderr)
        else:
            print("ok  %s" % skill_dir.name)

    print("\n%d skill(s), %d invalid" % (len(skill_dirs), failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
