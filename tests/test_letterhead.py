"""
The JSA letterhead on the printed letter.

Ross had been adding the logo and the 50-year mark to each letter by hand after
the generator produced it, which is a step that gets forgotten on the morning
someone is in a hurry. Both are now part of every letter the generator makes.

EMBEDDED, NOT LINKED, and that is the part worth protecting. The PDF is made by
headless Edge and then emailed: a relative <img src="assets/..."> resolves
against wherever the HTML happens to sit, a jpsi.com URL needs the network at
print time and degrades to a broken-image box if it is slow, and neither
survives the file being forwarded. A data URI is part of the document.

    python -m pytest tests/test_letterhead.py -q
"""
from __future__ import annotations

from datetime import date

import pytest

from letter import render

REPO = render.Path(__file__).resolve().parent.parent


def _ctx(kind="am", session="am"):
    return {"kind": kind, "session": session, "issue_date": date(2026, 9, 24),
            "change_basis": "week", "live_cattle": [], "feeder_cattle": [],
            "cash": {}, "cutout": {}, "slaughter": {}, "commentary": {}}


def test_both_assets_are_in_the_repo():
    """The 50-year mark was copied in from basis-tracker; it must travel."""
    assert (REPO / "assets" / "logo-full.png").exists()
    assert (REPO / "assets" / "jsa-50-years.png").exists()


@pytest.mark.parametrize("kind,session", [("am", "am"), ("tuesday", "pm"), ("friday", "pm")])
def test_every_letter_carries_the_letterhead(kind, session):
    """Same company writing, morning or evening."""
    html = render.build_html(_ctx(kind, session))
    assert 'class="wm"' in html, "no watermark"
    assert 'alt="John Stewart and Associates"' in html, "no masthead logo"


def test_the_images_are_embedded_not_linked():
    html = render.build_html(_ctx())
    assert "data:image/png;base64," in html
    assert "jpsi.com/wp-content" not in html, "a network image would break when forwarded"
    assert 'src="assets/' not in html, "a relative path breaks once the file moves"


def test_the_watermark_is_behind_the_text_and_can_stay_there():
    """
    z-index -1 only works because the page background is on <html>. Move it to
    <body> and the watermark vanishes underneath it -- silently, and only in the
    PDF, which is the worst place to find out.
    """
    css = (REPO / "letter" / "render.py").read_text(encoding="utf-8")
    assert "html { background: #fff; }" in css
    assert "z-index: -1" in css
    # body must not gain its own background
    body_rule = css[css.index("body {"):css.index("body {") + 260]
    assert "background" not in body_rule


def test_the_watermark_costs_no_layout():
    """
    position:fixed keeps it out of flow, which is why letterhead does not spend
    the morning brief's one-page budget. A static or floated mark would.
    """
    css = (REPO / "letter" / "render.py").read_text(encoding="utf-8")
    wm = css[css.index(".wm {"):css.index(".wm {") + 200]
    assert "position: fixed" in wm


def test_a_missing_asset_does_not_cost_the_letter(monkeypatch):
    """Letterhead is presentation. Losing it must never cost the numbers."""
    render._asset_uri.cache_clear()
    monkeypatch.setattr(render, "_asset_uri", lambda name: "")
    html = render.build_html(_ctx())
    assert "JSA AM Daily Cattle Report 9/24/26" in html
    assert 'class="wm"' not in html
    assert "<img" not in html.split("<h2>")[0] or "data:image" not in html


def test_the_asset_loader_is_cached():
    """A 36KB base64 string re-encoded on every render would be silly."""
    render._asset_uri.cache_clear()
    first = render._asset_uri("logo-full.png")
    render._asset_uri("logo-full.png")
    assert render._asset_uri.cache_info().hits >= 1
    assert first.startswith("data:image/png;base64,")


def test_a_missing_file_returns_empty_rather_than_raising():
    assert render._asset_uri("no-such-file.png") == ""
