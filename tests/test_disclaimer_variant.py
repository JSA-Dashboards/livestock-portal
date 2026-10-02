"""
Two copies of the letter, and only one carries the risk disclaimer.

Ross emails the letter inside a message that already carries the firm's risk
disclaimer, so the attached PDF and image print it a second time. One variant
drops it — for that attachment and nothing else.

THE DEFAULT IS ALWAYS TO INCLUDE IT. `disclaimer` is keyword-only and True, so
the CLI, a --no-fetch re-render and --archive all keep the full letter without
being touched. Only the authoring page may turn it off, per render, with the
state shown on screen and reset every run. A disclaimer that goes missing
quietly is the one failure here that matters.
"""
import re
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from letter import config, render  # noqa: E402

FIRST_WORDS = config.DISCLAIMER.format(year=2026)[:40]


def _ctx(kind="am", session="am"):
    # Same shape test_letterhead uses — build_html needs change_basis and the
    # four data dicts, not just the commentary.
    return {"kind": kind, "session": session, "issue_date": date(2026, 10, 2),
            "change_basis": "week", "live_cattle": [], "feeder_cattle": [],
            "cash": {}, "cutout": {}, "slaughter": {}, "commentary": {}}


@pytest.mark.parametrize("kind,session", [("am", "am"), ("recap", "pm"),
                                          ("tuesday", "pm"), ("friday", "pm")])
def test_the_disclaimer_is_there_by_default(kind, session):
    """Every format, no argument passed — the way the CLI calls it."""
    assert FIRST_WORDS in render.build_html(_ctx(kind, session))


@pytest.mark.parametrize("kind,session", [("am", "am"), ("recap", "pm"),
                                          ("tuesday", "pm"), ("friday", "pm")])
def test_it_can_be_left_off_in_every_format(kind, session):
    html = render.build_html(_ctx(kind, session), disclaimer=False)
    assert FIRST_WORDS not in html
    assert 'class="disclaimer"' not in html


@pytest.mark.parametrize("kind,session", [("am", "am"), ("friday", "pm")])
def test_nothing_else_about_the_letter_changes(kind, session):
    """
    Only the disclaimer goes. The signature, the letterhead and every figure
    must be identical, or this is a different letter rather than the same one
    without six lines of small print.
    """
    with_d = render.build_html(_ctx(kind, session))
    without = render.build_html(_ctx(kind, session), disclaimer=False)
    # strip the disclaimer div out of the full copy; the rest must match
    stripped = re.sub(r'<div class="disclaimer">.*?</div>', "", with_d, flags=re.S)
    assert stripped == without


def test_the_signature_itself_survives():
    html = render.build_html(_ctx(), disclaimer=False)
    for field in ("name", "company", "city", "web"):
        assert config.SIGNATURE[field] in html


def test_the_flag_is_keyword_only():
    """
    Positional would make `build_html(ctx, something)` silently drop the
    disclaimer. Thirty-odd callers pass one argument; none of them should be
    able to turn this off by accident.
    """
    with pytest.raises(TypeError):
        render.build_html(_ctx(), False)


def test_the_cli_never_passes_it():
    """
    letter/build.py renders the copy that --archive publishes. It must not
    acquire this argument: the archive is the record of what was sent, and a
    letter on file without its disclaimer is the wrong record.
    """
    src = (ROOT / "letter" / "build.py").read_text(encoding="utf-8")
    src = re.sub(r'"""(.*?)"""', "", src, flags=re.S)
    src = re.sub(r"#.*", "", src)
    assert "disclaimer" not in src
