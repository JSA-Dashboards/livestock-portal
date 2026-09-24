"""
The chart of the day on the morning brief.

THE CONSTRAINT IS THE FEATURE. Ross asked for a chart in the bottom-right "only
if it can stay to 1 page", and CLAUDE.md already called the morning brief's one
page "the product". The AM letter was measured before any of this was written:
8.28in of content in a 9.2in printable area -- 0.92in of slack, which a 1.63in
chart does not fit into.

It fits anyway because it does not go BELOW anything. The band to the right of
the signature block measured 1.89in tall and 4.97in wide and was entirely empty,
so the chart floats into space that already existed and the page grew by 0.22in
rather than 1.63in. That is the whole design, and it is why the tests below care
about the float and the height rather than about how pretty the line is.

    python -m pytest tests/test_chart.py -q

Offline. The real proof is a rendered PDF with one page, and there is a test for
that at the bottom which skips when no browser is installed.
"""
from __future__ import annotations

import re
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from letter import chart, render, topdf

REPO = Path(__file__).resolve().parent.parent

# The empty band beside the signature, measured in the browser at the letter's
# real print width. The chart has to live inside this.
FREE_BAND_IN = 1.89
FREE_BAND_WIDE_IN = 4.97


def _series(n=60, start=368.0):
    d0 = date(2026, 6, 22)
    return ([d0 + timedelta(days=i) for i in range(n)],
            [start - i * 0.5 + (i % 7) * 1.5 for i in range(n)])


# -- The one-page constraint, encoded ------------------------------------------

def test_the_chart_fits_the_empty_band():
    """Grow it past this and the letter runs to two pages."""
    assert chart.HEIGHT_IN <= FREE_BAND_IN, "taller than the space beside the signature"
    assert chart.WIDTH_IN <= FREE_BAND_WIDE_IN


def test_it_floats_so_it_costs_no_vertical_space():
    """
    The float is load-bearing, not styling. Without it the chart becomes a block
    element, stops sharing the line with the signature, and adds its full height
    to a page that has 0.92in to give.
    """
    css = (REPO / "letter" / "render.py").read_text(encoding="utf-8")
    assert ".dayplot-wrap { float: right;" in css


def test_the_chart_sits_before_the_signoff_in_source_order():
    """That is what puts a right float in the bottom-right corner."""
    src = (REPO / "letter" / "render.py").read_text(encoding="utf-8")
    body = src[src.index('if kind == "am":'):]
    assert body.index("chart_block") < body.index('class="signoff"')


# -- Which letters get it ------------------------------------------------------

def _ctx(kind, session, chart_data=None):
    return {"kind": kind, "session": session, "issue_date": date(2026, 9, 24),
            "change_basis": "week" if session == "pm" else "day",
            "live_cattle": [], "feeder_cattle": [], "fci": {"value": 337.0, "change": 0.5},
            "cash": {}, "cutout": {}, "slaughter": {}, "commentary": {},
            "chart": chart_data or {}}


def test_the_morning_brief_gets_it():
    dates, values = _series()
    html = render.build_html(_ctx("am", "am", {"title": "Sep Feeder Cattle", "dates": dates,
                                               "values": values}))
    assert 'class="dayplot-wrap"' in html and "<svg" in html


@pytest.mark.parametrize("kind", ["tuesday", "friday"])
def test_the_evening_letters_do_not(kind):
    """
    Asked for on the AM report only. gather() populates ctx["chart"] for am
    alone, and build_html draws it inside the AM branch -- both, so neither one
    being changed quietly puts a chart on the evening letter.
    """
    dates, values = _series()
    html = render.build_html(_ctx(kind, "pm", {"title": "x", "dates": dates, "values": values}))
    # The ELEMENT, not the string: the stylesheet is shared by all three
    # formats, so ".dayplot-wrap" appears in every letter's <style> block and
    # proves nothing about what was drawn.
    assert 'class="dayplot-wrap"' not in html
    assert "<svg" not in html


def test_gather_only_fetches_the_series_for_am():
    src = (REPO / "letter" / "build.py").read_text(encoding="utf-8")
    block = src[src.index('ctx["chart"]') - 200:src.index('ctx["chart"]') + 80]
    assert 'if kind == "am"' in block


# -- Drawing -------------------------------------------------------------------

def test_the_axis_hugs_the_data():
    """
    The first version floored to a multiple of the step from zero, so feeders
    ranging 318.98-371.38 got an axis of 300-400: the line used half the plot
    height and a 52-point slide read as a drift. A chart that understates the
    move it exists to show is worse than no chart.
    """
    lo, hi, ticks = chart._nice_bounds(318.98, 371.38)
    coverage = (371.38 - 318.98) / (hi - lo)
    assert coverage > 0.65, f"data uses only {coverage:.0%} of the axis"
    assert len(ticks) == 3


def test_a_flat_series_does_not_divide_by_zero():
    lo, hi, _ = chart._nice_bounds(300.0, 300.0)
    assert hi > lo
    assert chart.line_chart(*_series(10, 300.0), "flat")


def test_dates_survive_the_json_cache():
    """
    THE NORMAL PATH. build.py caches ctx to JSON between the fetch run and the
    --no-fetch re-render that actually makes the PDF, and JSON has no date type.
    Slicing the returned strings for a month label printed "202".
    """
    assert chart._as_date("2026-06-22") == date(2026, 6, 22)
    assert chart._as_date(date(2026, 6, 22)) == date(2026, 6, 22)
    assert chart._as_date("not a date") is None

    dates, values = _series()
    svg = chart.line_chart([d.isoformat() for d in dates], values, "cached")
    assert ">Jun<" in svg and ">Aug<" in svg
    assert ">202<" not in svg


def test_too_little_data_draws_nothing():
    """Two points is not a chart; better absent than misleading."""
    assert chart.line_chart([date(2026, 9, 1)], [1.0], "x") == ""
    assert chart.chart_block({}) == ""
    assert chart.chart_block({"dates": [], "values": []}) == ""


def test_only_the_endpoint_is_labelled():
    """A number on every point is unreadable at three inches wide."""
    dates, values = _series()
    svg = chart.line_chart(dates, values, "Sep Feeder Cattle")
    # 3 axis ticks + 2 month labels + 1 title + 1 endpoint value
    assert len(re.findall(r"<text", svg)) <= 8


def test_gridlines_are_solid_hairlines():
    """Dashed grid reads as a threshold or a projection when it is just a grid."""
    svg = chart.line_chart(*_series(), "x")
    assert "stroke-dasharray" not in svg
    assert 'stroke-width="1"' in svg


def test_the_drawer_cannot_fetch():
    """Same rule render.py lives under: it draws what it is given."""
    src = (REPO / "letter" / "chart.py").read_text(encoding="utf-8")
    assert "import requests" not in src
    assert "sources" not in src


# -- The real proof ------------------------------------------------------------

@pytest.mark.skipif(not topdf.find_browser(), reason="no browser to render a PDF")
def test_the_rendered_pdf_is_one_page(tmp_path):
    """
    The constraint as Ross stated it. Skipped where there is no Edge or Chrome
    -- including Streamlit Cloud, and including a desktop where Edge is already
    busy, which is exactly what happened while this was being written.
    """
    pytest.importorskip("pypdf")
    from pypdf import PdfReader

    dates, values = _series()
    ctx = _ctx("am", "am", {"title": "Sep Feeder Cattle — 60 sessions",
                            "dates": dates, "values": values})
    ctx["commentary"] = {"headlines": ["A headline of roughly the length Ross writes, "
                                       "which is most of a line", "And a second one"]}
    html_path = tmp_path / "letter.html"
    pdf_path = tmp_path / "letter.pdf"
    html_path.write_text(render.build_html(ctx), encoding="utf-8")
    ok, msg = topdf.html_to_pdf(html_path, pdf_path)
    if not ok:
        pytest.skip(f"browser present but would not render: {msg}")
    assert len(PdfReader(str(pdf_path)).pages) == 1, "the chart pushed the brief to two pages"
