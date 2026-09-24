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

from letter import chart, config, render, topdf

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


# -- Which chart, and why ------------------------------------------------------

ISSUE = date(2026, 9, 24)


@pytest.mark.parametrize("text,expected", [
    ("Packers slow kills as the cutout slips", "live"),
    ("Fed cattle trade develops in the north", "live"),
    ("Feeder calves steady at the barns", "feeders"),
    ("Screwworm ban eased on Mexican cattle", "feeders"),
    ("Border reopens at Douglas", "feeders"),
    ("Cost of gain keeps backgrounders sidelined", "corn"),
    ("Crude spikes on OPEC headlines", "crude"),
    ("Equities sell off on recession talk", "sp"),
])
def test_the_text_picks_the_chart(text, expected):
    entry, reason = chart.pick(ISSUE, text)
    assert entry["key"] == expected, f"{text!r} -> {entry['key']} ({reason})"
    assert "matched" in reason


def test_a_crop_harvest_is_not_a_kill_floor():
    """
    The miss that produced the weighting. "harvest" was in the Live Cattle words
    for the packer sense, so "Corn basis firms as harvest rolls" tied three ways
    on one hit each and the tie-break handed it to Live Cattle.
    """
    entry, _ = chart.pick(ISSUE, "Corn basis firms as harvest rolls")
    assert entry["key"] == "corn"


def test_a_phrase_outranks_a_bare_word():
    """"cost of gain" says more about the morning than a stray "corn"."""
    entry, _ = chart.pick(ISSUE, "corn cost of gain")
    assert entry["key"] == "corn"
    entry, _ = chart.pick(ISSUE, "fed cattle and a calf")
    assert entry["key"] == "live"


# -- Tier 2: the day's candidate headlines -------------------------------------

def _cands():
    """One realistic morning's panel: many topics, mixed sources."""
    return [
        {"source": "USDA border report",
         "title": "Douglas, AZ - steer calves and yearlings sold steady, Mexican cattle"},
        {"source": "Beef Magazine", "title": "Cattle futures drop on export rumors"},
        {"source": "Tri-City Herald", "title": "Latest on Tyson beef plant: industry watching"},
        {"source": "meat+poultry", "title": "Illinois seeks buyer for Tyson Foods beef plant"},
        {"source": "Politico", "title": "Trump officials weigh rolling back beef import plan"},
    ]


def test_the_days_headlines_aim_the_chart_before_anything_is_typed():
    """The point of the tier: open the page, press Fetch, chart is already aimed."""
    entry, reason = chart.pick(ISSUE, "", _cands())
    assert entry["key"] == "live"
    assert "the day's headlines" in reason
    assert "Tyson" in reason          # says WHICH headline did it


def test_what_you_typed_still_beats_the_whole_candidate_pile():
    entry, reason = chart.pick(ISSUE, "Corn and cost of gain", _cands())
    assert entry["key"] == "corn" and "in your text" in reason


def test_a_packer_name_is_a_fed_cattle_story():
    """
    _RELEVANT has carried the packer names since the Kansas miss. Leaving them
    out of the chart pool meant three Tyson plant stories in one morning scored
    zero for Live Cattle and a single border line outvoted them.
    """
    assert chart._score("Tyson Foods beef plant sold", {"words":
                        dict(config.CHART_POOL[1])["words"]}) > 0


@pytest.mark.parametrize("source,expected", [
    ("USDA AMS cash trade", 3.0),
    ("USDA border report", 3.0),
    ("Beef Magazine", 2.0),
    ("Meatingplace", 2.0),
    ("Reuters", 1.0),
    ("Politico", 1.0),
    ("Some Local Paper Nobody Has Seen", 1.0),
])
def test_sources_are_weighted_by_how_much_they_know(source, expected):
    assert chart.source_weight(source) == expected


def test_one_usda_line_outranks_a_lone_general_newsroom():
    """Same content, different desks: USDA's cattle-specific report wins."""
    same = "Mexican cattle and steer calves at the border"
    usda = chart.pick(ISSUE, "", [{"source": "USDA border report", "title": same},
                                  {"source": "Reuters", "title": "Crude oil and OPEC energy"}])
    assert usda[0]["key"] == "feeders"


def test_an_empty_candidate_list_falls_through():
    entry, reason = chart.pick(ISSUE, "", [], {"crude": 0.02})
    assert "biggest mover" in reason


def test_the_candidate_tier_can_never_trigger_a_fetch():
    """
    Several HTTP calls behind every build, for a chart choice, would be a bad
    trade. The list is passed in only when the caller already has it.
    """
    # The IMPORT, not the word -- "headlines" appears all over the prose here.
    src = (REPO / "letter" / "chart.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from \.? ?import|import)\s+.*headlines", src, re.M)
    assert not re.search(r"^\s*from \. import .*headlines", src, re.M)

    # build.py takes the list as an argument and never goes and gets one.
    build = (REPO / "letter" / "build.py").read_text(encoding="utf-8")
    assert "candidates: list = None" in build
    assert "headlines.candidates(" not in build


def test_no_text_falls_to_the_biggest_mover():
    entry, reason = chart.pick(ISSUE, "", None, {"live": 0.001, "corn": -0.030, "sp": 0.004})
    assert entry["key"] == "corn" and "biggest mover" in reason


def test_movers_are_compared_as_fractions_not_points():
    """40 S&P points is a smaller day than 8 cents of corn; only the ratio knows."""
    entry, _ = chart.pick(ISSUE, "", None, {"sp": 40 / 7772.5, "corn": 8 / 529.0})
    assert entry["key"] == "corn"


def test_nothing_to_go_on_falls_to_a_rotation():
    entry, reason = chart.pick(ISSUE, "", None, {})
    assert reason == "rotation" and entry in chart.config.CHART_POOL


def test_the_same_day_always_picks_the_same_chart():
    """
    NOT RANDOM AT RENDER TIME. The letter is built twice -- once to fetch, once
    with --no-fetch to make the PDF -- so a genuinely random pick would put a
    different chart in the PDF than the one that was previewed.
    """
    for _ in range(5):
        assert chart.pick(ISSUE, "")[0]["key"] == chart.pick(ISSUE, "")[0]["key"]


def test_each_cycle_shows_everything_once():
    """
    The guarantee is PER CYCLE, and a cycle is aligned to the ordinal, not to
    whatever day you start counting from. An arbitrary five-day window can
    straddle a boundary and legitimately repeat one chart at each end -- what it
    can never do is repeat on consecutive days, which is the next test.
    """
    n = len(chart.config.CHART_POOL)
    start = ISSUE
    while start.toordinal() % n:            # step to a cycle boundary
        start += timedelta(days=1)
    for c in range(3):
        cycle = [chart.pick(start + timedelta(days=c * n + i), "")[0]["key"]
                 for i in range(n)]
        assert len(set(cycle)) == n, f"cycle {c} repeated itself: {cycle}"


def test_every_chart_comes_round_inside_a_fortnight():
    """The point of the feature: a different chart, and all of them regularly."""
    n = len(chart.config.CHART_POOL)
    seen = {chart.pick(ISSUE + timedelta(days=i), "")[0]["key"] for i in range(14)}
    assert len(seen) == n, f"only saw {sorted(seen)} in two weeks"


def test_the_rotation_never_repeats_two_days_running():
    days = [chart.pick(ISSUE + timedelta(days=i), "")[0]["key"] for i in range(40)]
    assert all(a != b for a, b in zip(days, days[1:])), days


def test_corn_is_written_in_eighths_like_the_bullets():
    """529.25 on the chart beside 529'1 in the text would read as two numbers."""
    dates, values = _series(20, 529.25)
    svg = chart.line_chart(dates, values, "Dec Corn", style="eighths")
    assert "'" in svg or ">529<" in svg
    assert "529.25" not in svg


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
