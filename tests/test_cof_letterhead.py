"""The COF Recap's letterhead, and the four ways it would go wrong quietly.

Ross prints this page and sends it to the same clients who get the daily
letter, so it carries the letter's stationery: wordmark top-right, the
50-years roundel faint behind the table, a hairline sage frame. None of that
is imported from letter/render.py — that module builds an 8.5x11in HTML
document and this is a 520x690 Plotly figure, so only the geometry is shared.

Which is exactly the risk. Nothing connects the two files, so:

  * **The frame could drift off the letter's sage.** Pinned by importing
    letter.config and comparing, so changing the letter's frame colour fails
    HERE rather than producing two subtly different pieces of stationery.
  * **An image could stretch.** sizex and sizey are fractions of two different
    lengths, so passing one number for both squashes the wordmark into
    something that still renders and is still obviously the logo.
  * **A source could become a path.** The figure is serialised to JSON and
    handed to kaleido in a SEPARATE PROCESS, so a relative path resolves
    against whatever directory that process is in — a silently image-less
    export that renders perfectly.
  * **The footer could sit under the frame line.** At FIG_H-20 it did, and at
    export scale it read as struck through.

    python -m pytest tests/test_cof_letterhead.py -q
"""

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "apps" / "cattle_on_feed"))
sys.path.insert(0, str(_ROOT))

import cof_recap  # noqa: E402
from letter import config as letter_config  # noqa: E402


RECAP = {
    "title": "Oct COF Report",
    "month": 10, "year": 2026,
    "release_date": None,
    "placement_month": "September 2026",
    "actual":   {"on_feed": 99.6, "placed": 87.9, "marketed": 93.4},
    "year_ago": {"on_feed": 98.9, "placed": 90.1, "marketed": 86.4},
    "states": [("IA", 97, 92), ("NE", 100, 84)],
    "weight_classes": [("Under 600#", 360000, "July/Aug")],
    "placed_total": 1_777_000,
}


def _fig(**over):
    rec = dict(RECAP, **over)
    return cof_recap.build_figure(rec, guesses={}, footer=True)


def _images(fig):
    return {("wm" if im.layer == "below" else "logo"): im for im in fig.layout.images}


# ── it must not drift from the letter ────────────────────────────────────────

def test_the_frame_is_the_letter_s_own_sage():
    """letter/config.py is the authority. If the letter restyles, this fails."""
    assert cof_recap.BRAND_SAGE == letter_config.FRAME
    assert f"{cof_recap.FRAME_PT}pt" == letter_config.FRAME_WIDTH


def test_the_watermark_keeps_the_letter_s_opacity_and_height():
    """.wm is opacity 0.07 at top 46% — faint and behind, not a graphic."""
    assert cof_recap.WM_OPACITY == 0.07
    assert cof_recap.WM_CENTRE_Y == 0.46
    wm = _images(_fig())["wm"]
    assert wm.opacity == 0.07
    assert wm.layer == "below"
    assert wm.y == pytest.approx(1 - 0.46)


# ── the figure it actually builds ────────────────────────────────────────────

def test_it_draws_a_wordmark_a_watermark_and_a_frame():
    fig = _fig()
    assert len(fig.layout.images) == 2, "expected the wordmark and the watermark"
    assert len(fig.layout.shapes) == 1, "expected exactly the frame"
    shape = fig.layout.shapes[0]
    assert shape.type == "rect"
    assert shape.line.color == letter_config.FRAME
    assert shape.layer == "below"


@pytest.mark.parametrize("key,asset", [("wm", "jsa-50-years.png"),
                                       ("logo", "logo-full.png")])
def test_neither_image_is_stretched(key, asset):
    """sizex and sizey are fractions of DIFFERENT lengths.

    Rendered pixel width / height must come back to the asset's own aspect,
    or the wordmark is squashed and still perfectly legible.
    """
    _, aspect = cof_recap._asset(asset)
    im = _images(_fig())[key]
    px_w = im.sizex * cof_recap.FIG_W
    px_h = im.sizey * cof_recap.FIG_H
    assert px_w / px_h == pytest.approx(aspect, rel=1e-6)


@pytest.mark.parametrize("asset", ["jsa-50-years.png", "logo-full.png"])
def test_sources_are_embedded_not_paths(asset):
    """kaleido renders in another process; a path resolves against its cwd."""
    uri, _ = cof_recap._asset(asset)
    assert uri.startswith("data:image/png;base64,")
    for im in _fig().layout.images:
        assert im.source.startswith("data:image/png;base64,"), im.source[:60]


def test_the_png_size_is_read_from_the_file():
    """The aspect must track the asset, not a constant someone wrote down."""
    for name, expect in (("logo-full.png", (222, 60)),
                         ("jsa-50-years.png", (272, 249))):
        raw = (_ROOT / "assets" / name).read_bytes()
        assert cof_recap._png_size(raw) == expect


def test_a_missing_asset_costs_the_branding_and_not_the_page():
    """Letterhead is presentation; losing it must not cost the numbers."""
    cof_recap._asset.cache_clear()
    try:
        uri, aspect = cof_recap._asset("no-such-file.png")
        assert (uri, aspect) == ("", 0.0)
    finally:
        cof_recap._asset.cache_clear()


# ── geometry that only a render would otherwise catch ────────────────────────

def test_the_footer_clears_the_frame():
    """At FIG_H-20 the baseline sat inside a line drawn FRAME_INSET from the
    edge and read as struck through at export scale."""
    # The footer is the lowest annotation on the page; compare it in pixels
    # against the frame line rather than trusting the constant.
    lowest = min(a["y"] for a in _fig().layout.annotations)
    footer_px = (1 - lowest) * cof_recap.FIG_H
    assert footer_px < cof_recap.FIG_H - cof_recap.FRAME_INSET, (
        "the lowest annotation sits on or below the frame line")
    assert cof_recap.FIG_H - cof_recap.FRAME_INSET - footer_px >= 8, (
        "the lowest annotation is within 8px of the frame line")


def test_the_frame_does_not_crowd_the_first_column():
    """The letter's 0.52in taken literally lands 2px off the table."""
    text_left = 34   # where every left-aligned annotation starts
    assert cof_recap.FRAME_INSET < text_left
    assert text_left - cof_recap.FRAME_INSET >= 15, (
        "the frame reads as a box drawn round the table")


# ── the empty year-ago column ────────────────────────────────────────────────

def _notes(fig):
    return [a["text"] for a in fig.layout.annotations if "report published" in a["text"]]


def test_an_empty_year_ago_column_says_why():
    """Three bare em-dashes on a client page read as a broken fetch."""
    notes = _notes(_fig(year_ago={}))
    assert notes == ["No Oct 2025 report published"], notes


def test_a_populated_year_ago_column_says_nothing():
    assert _notes(_fig()) == []


def test_the_note_names_the_year_before_the_report():
    """Not 'last year' and not this year — the month that is missing."""
    assert _notes(_fig(year_ago={}, month=1, year=2027)) == \
        ["No Jan 2026 report published"]
