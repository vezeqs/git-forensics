#!/usr/bin/env python3
"""Render the README images from a real run of examples/demo.sh.

Nothing here is hand-drawn. The script executes the demo, splits its output
into sections, and renders each section as a terminal capture (SVG) plus an
animated GIF of the regression hunt. If the tools change, the images change.

Requires Pillow, which is a build-time dependency only. The skills themselves
use the standard library.

Usage: python3 tools/render_assets.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
DEMO = REPO_ROOT / "examples" / "demo.sh"
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")

BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
TEXT = "#c9d1d9"
DIM = "#8b949e"
GREEN = "#7ee787"
BLUE = "#79c0ff"
PURPLE = "#d2a8ff"
ORANGE = "#ffa657"

SECTION = re.compile(r"^== (.+?) ==$", re.MULTILINE)
SKIP_LINE = re.compile(r"^(- Duration:|Repository: )")


def capture():
    proc = subprocess.run(
        ["sh", str(DEMO)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise SystemExit("demo.sh failed:\n%s" % proc.stderr)
    return proc.stdout


def split_sections(text):
    matches = list(SECTION.finditer(text))
    sections = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        sections[match.group(1)] = [
            line for line in body.splitlines()
            if line.strip() and not SKIP_LINE.match(line)
        ]
    return sections


def wrap_lines(lines, limit=112):
    """Wrap long lines the way a terminal would, with a hanging indent."""
    result = []
    for line in lines:
        remaining = line
        while len(remaining) > limit:
            cut = remaining.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            result.append(remaining[:cut])
            remaining = "  " + remaining[cut:].lstrip()
        result.append(remaining)
    return result


def trim(lines, limit=34):
    """Keep the part a reader needs, and say when the rest was cut."""
    if len(lines) <= limit:
        return lines
    return lines[: limit - 1] + ["... (truncated)"]


def colour_for(line):
    stripped = line.lstrip()
    if stripped.startswith("# "):
        return BLUE
    if stripped.startswith("## "):
        return BLUE
    if stripped.startswith("error:") or stripped.startswith("- origin"):
        return ORANGE
    if stripped.startswith(">"):
        return GREEN
    if stripped.startswith("|"):
        return DIM
    if stripped.startswith("- Good") or stripped.startswith("- Bad"):
        return GREEN
    return TEXT


def svg_capture(title, lines, path, font_size=14, line_height=21):
    lines = wrap_lines(lines)
    padding = 26
    header = 38
    char_width = font_size * 0.62
    widest = max((len(line) for line in lines), default=40)
    width = int(min(max(widest * char_width + padding * 2, 560), 1180))
    height = int(header + padding + len(lines) * line_height + padding)

    out = []
    out.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" role="img" aria-label="%s">'
        % (width, height, width, height, escape(title))
    )
    out.append(
        '<rect x="0.5" y="0.5" width="%d" height="%d" rx="8" fill="%s" stroke="%s"/>'
        % (width - 1, height - 1, BG, BORDER)
    )
    out.append('<path d="M0 38 H%d" stroke="%s"/>' % (width, BORDER))
    out.append(
        '<circle cx="20" cy="19" r="5" fill="#ff5f56"/>'
        '<circle cx="38" cy="19" r="5" fill="#ffbd2e"/>'
        '<circle cx="56" cy="19" r="5" fill="#27c93f"/>'
    )
    out.append(
        '<text x="76" y="24" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
        'font-size="12" fill="%s">%s</text>' % (DIM, escape(title))
    )

    y = header + padding + font_size
    for line in lines:
        colour = colour_for(line)
        weight = ' font-weight="bold"' if line.lstrip().startswith("#") else ""
        out.append(
            '<text x="%d" y="%d" xml:space="preserve" '
            'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
            'font-size="%d" fill="%s"%s>%s</text>'
            % (padding, y, font_size, colour, weight, escape(line))
        )
        y += line_height

    out.append("</svg>")
    path.write_text("\n".join(out) + "\n")
    return path


def gif_capture(lines, path, font_size=15, line_height=22):
    from PIL import Image, ImageDraw, ImageFont

    lines = wrap_lines(lines)
    padding = 28
    header = 40
    font = ImageFont.truetype(str(FONT_PATH), font_size)
    bold = ImageFont.truetype(str(FONT_PATH), font_size)
    small = ImageFont.truetype(str(FONT_PATH), 12)

    widest = max(len(line) for line in lines)
    char_width = font.getlength("M")
    width = int(min(max(widest * char_width + padding * 2, 620), 1180))
    height = int(header + padding + len(lines) * line_height + padding)

    def frame(count):
        image = Image.new("RGB", (width, height), BG)
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, width - 1, height - 1], outline=BORDER, width=1)
        draw.line([0, header, width, header], fill=BORDER)
        for cx, colour in ((20, "#ff5f56"), (38, "#ffbd2e"), (56, "#27c93f")):
            draw.ellipse([cx - 5, 14, cx + 5, 24], fill=colour)
        draw.text((76, 13), "regression-hunt", font=small, fill=DIM)

        y = header + padding
        for line in lines[:count]:
            draw.text((padding, y), line, font=bold if line.startswith("#") else font,
                      fill=colour_for(line))
            y += line_height
        if count < len(lines):
            draw.rectangle([padding, y + 2, padding + char_width, y + line_height - 2],
                           fill=GREEN)
        return image

    steps = [1]
    index = 1
    while index < len(lines):
        index += 2
        steps.append(min(index, len(lines)))

    images = [frame(count) for count in steps]
    durations = [170] * (len(images) - 1) + [3200]
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    return path


def main():
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Pillow is required to render the images:\n"
            "  python3 -m pip install -r requirements-dev.txt"
        )
    if not FONT_PATH.exists():
        raise SystemExit(
            "missing font: %s\nInstall the DejaVu fonts (package: fonts-dejavu)." % FONT_PATH
        )

    DOCS.mkdir(exist_ok=True)

    sections = split_sections(capture())
    hunt = trim(sections["regression-hunt: which commit broke parse_duration?"])
    blame = trim(sections["blame-archaeology: why does this line exist?"])
    preflight = trim(
        sections["regression-hunt: what happens with a command that is broken everywhere?"],
        limit=8,
    )

    # An empty section renders an empty panel, which is worse than failing.
    for name, lines in (("hunt", hunt), ("blame", blame), ("preflight", preflight)):
        if not lines:
            raise SystemExit("section %r is empty; the demo output changed" % name)

    prompt = [
        "$ python3 scripts/hunt.py --good v0.1.0 --bad HEAD --cmd 'python3 check.py'",
        "",
    ]

    # Render into a staging directory and move files into place only when every
    # image succeeded, so a failure cannot leave docs/ half-regenerated.
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(DOCS)))
    names = ("regression-hunt.svg", "blame-archaeology.svg", "preflight.svg", "demo.gif")
    try:
        svg_capture("regression-hunt", prompt + hunt, staging / names[0])
        svg_capture("blame-archaeology", blame, staging / names[1])
        svg_capture("preflight", preflight, staging / names[2])
        gif_capture(prompt + hunt, staging / names[3])
        for name in names:
            (staging / name).replace(DOCS / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    for name in names:
        path = DOCS / name
        print("%s (%d bytes)" % (path.relative_to(REPO_ROOT), path.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
