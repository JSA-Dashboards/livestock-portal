"""
The parts of the letter that stay Ross's: Market Action, the technical read and
the Fundamental Rundown.

These live in a plain markdown file per issue, one "## " heading per section,
bullets as "- ". The builder writes the file with the headings already in place
and the computed figures quoted underneath as HTML comments, so the numbers you
are writing about are in front of you while you write, and re-running the build
picks up whatever you saved without re-fetching anything.

An HTML comment is used for the hints on purpose: they are visible while editing
and cannot reach the rendered letter even if left in place.
"""
from __future__ import annotations

import re
from pathlib import Path

# Order matters -- this is the order the sections appear in each letter.
#
# The two letters do NOT share a section list. Friday replaces Market Action
# with Key Headlines, drops the Fundamental Rundown, and adds a Cash Trade Recap
# plus a Cattle on Feed note that is only used on release weeks. The technicals
# keys are shared on purpose, so a technical read typed for one carries the same
# meaning in the other.
SECTIONS_BY_KIND = {
    "tuesday": [
        ("market_action", "Market Action"),
        ("technicals_lc", "Technicals: Live Cattle"),
        ("technicals_fc", "Technicals: Feeder Cattle"),
        ("fundamental", "Fundamental Rundown"),
    ],
    "friday": [
        ("key_headlines", "Key Headlines"),
        ("technicals_lc", "Technicals: Live Cattle"),
        ("technicals_fc", "Technicals: Feeder Cattle"),
        ("cash_recap", "Cash Trade Recap"),
        ("cof_note", "Cattle on Feed Commentary"),
    ],
}

# Back-compatible alias. Callers that predate the Friday letter get Tuesday's.
SECTIONS = SECTIONS_BY_KIND["tuesday"]


def sections_for(kind: str = "tuesday") -> list:
    return SECTIONS_BY_KIND[kind]

_HEADING = re.compile(r"^##\s+(.*?)\s*$", re.MULTILINE)


def path_for(out_dir: Path, issue_date, kind: str = "tuesday") -> Path:
    """One draft per letter per day. The kind is in the NAME because the two
    letters have different sections -- a Tuesday draft read as Friday would
    silently drop Key Headlines and the Cash Trade Recap."""
    return Path(out_dir) / f"commentary_{kind}_{issue_date}.md"


def _hint_block(lines: list[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(f"  {ln}" for ln in lines)
    return f"<!-- computed for reference, not printed:\n{body}\n-->\n\n"


def write_template(path: Path, hints: dict, kind: str = "tuesday") -> None:
    """
    Create the editable file. Never overwrites: an existing file is your draft.
    """
    if path.exists():
        return
    parts = [
        "<!-- Your sections. Bullets as '- '. Blank sections are skipped in the",
        "     rendered letter, so you can drop one by leaving it empty. -->",
        "",
    ]
    for key, title in sections_for(kind):
        parts.append(f"## {title}")
        parts.append("")
        block = _hint_block(hints.get(key, []))
        if block:
            parts.append(block.rstrip("\n"))
            parts.append("")
        parts.append("- ")
        parts.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def read(path: Path, kind: str = "tuesday") -> dict:
    """
    Parse the markdown back into {key: [bullet, ...]}.

    Sections are matched on their HEADING TEXT, so reordering them in the file
    is harmless and an unrecognised heading is ignored rather than guessed at.
    """
    if not path.exists():
        return {key: [] for key, _ in sections_for(kind)}

    text = path.read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    by_title = {}
    matches = list(_HEADING.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        by_title[m.group(1).strip().lower()] = text[m.end():end]

    out = {}
    for key, title in sections_for(kind):
        body = by_title.get(title.lower(), "")
        bullets = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            # The template seeds each section with a bare "- ". An untouched one
            # must not reach the letter as an empty bullet.
            if line in ("-", "*"):
                continue
            # "- x" and "  - x" (a sub-bullet, kept with its indent intact so the
            # renderer can nest it the way Word's "o" level did).
            m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
            if m and m.group(2).strip():
                bullets.append(m.group(2).strip())
            elif not line.startswith("#"):
                bullets.append(line)
        out[key] = bullets
    return out


def write_sections(path: Path, sections: dict, kind: str = "tuesday") -> None:
    """
    Write {key: [bullet, ...]} back out in the same format read() parses.

    The Weekly Cattle Reports page edits in text areas; the CLI edits the file.
    Both must leave the file in one format or a letter half-written in one place
    cannot be finished in the other.
    """
    parts = []
    for key, title in sections_for(kind):
        parts.append(f"## {title}")
        parts.append("")
        for bullet in sections.get(key, []):
            text = str(bullet).strip()
            if text:
                parts.append(f"- {text}")
        parts.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def is_empty(sections: dict) -> bool:
    return not any(v for v in sections.values())
