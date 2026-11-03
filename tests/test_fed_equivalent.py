"""Guards for the Cattle Equivalent tab.

Every trap here produces a number that renders perfectly and is wrong, which is
why each test states the broken form's answer as arithmetic rather than
asserting only that the right one is right.
"""
from __future__ import annotations

import ast
import re
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "apps" / "beef_weight"
sys.path.insert(0, str(APP))

import fed_equivalent as fe  # noqa: E402

PAGE = APP / "app.py"
# apps/cattle_on_feed/app.py and apps/beef_trimmings/app.py both open with a
# UTF-8 BOM; ast.parse rejects it as "invalid non-printable character U+FEFF",
# which reads as a syntax error in the page rather than a codec choice in the
# reader. utf-8-sig is identical on files that have none.
PAGE_SRC = PAGE.read_text(encoding="utf-8-sig")
PAGE_AST = ast.parse(PAGE_SRC)
MOD_SRC = (APP / "fed_equivalent.py").read_text(encoding="utf-8")


def _weekly(rows):
    """rows: (week_ending, steer_head, steer_wt, heifer_head, heifer_wt)."""
    out = []
    for we, sh, sw, hh, hw in rows:
        for cls, head, wt in (("STEERS", sh, sw), ("HEIFERS", hh, hw)):
            out.append({"week_ending": we, "class_desc": cls,
                        "unit_desc": "HEAD", "Value": head})
            out.append({"week_ending": we, "class_desc": cls,
                        "unit_desc": "LB / HEAD, DRESSED BASIS", "Value": wt})
    return pd.DataFrame(out)


# ── the core arithmetic ──────────────────────────────────────────────────────

def test_head_equivalent_is_the_gain_over_the_baseline_not_over_today():
    # 20,000 head at 900 lb against an 850 lb baseline carries the beef of
    # 20,000 x 900/850 = 21,176 head, so +1,176.
    got = fe.head_equivalent(20_000, 900.0, 850.0)
    assert round(got) == 1176
    # Dividing by today's weight instead of the baseline gives 1,111 -- close
    # enough to pass a smell test, and wrong in every period.
    assert round(20_000 * (1 - 850.0 / 900.0)) == 1111 != round(got)


def test_a_weight_that_fell_returns_a_negative_not_a_zero():
    assert fe.head_equivalent(10_000, 800.0, 850.0) < 0


def test_a_missing_baseline_returns_none_rather_than_dividing():
    assert fe.head_equivalent(10_000, 900.0, 0) is None
    assert fe.head_equivalent(0, 900.0, 850.0) is None


# ── head-weighting ───────────────────────────────────────────────────────────

def test_the_fed_carcass_is_head_weighted_across_the_two_classes():
    w = fe.fed_weekly(_weekly([("2026-01-03", 60_000, 950.0, 40_000, 870.0)]))
    got = float(w["fed_carcass_lb"].iloc[0])
    assert got == pytest.approx((60_000 * 950 + 40_000 * 870) / 100_000)
    assert got == pytest.approx(918.0)
    # The unweighted mean of the two class figures is 910 -- 8 lb light here,
    # and about 15 lb light on the real 3:2 split.
    assert (950.0 + 870.0) / 2 == 910.0 != pytest.approx(got)


def test_weeks_are_head_weighted_too_never_a_mean_of_weekly_averages():
    w = fe.fed_weekly(_weekly([
        ("2026-01-03", 90_000, 900.0, 10_000, 900.0),   # 100k head at 900
        ("2026-01-10", 5_000, 1000.0, 5_000, 1000.0),   # 10k head at 1000
    ]))
    got = fe.ytd(w, 2026)["fed_carcass_lb"]
    assert got == pytest.approx((100_000 * 900 + 10_000 * 1000) / 110_000)
    assert got == pytest.approx(909.09, abs=0.01)
    # Averaging the two weekly averages gives 950 -- a light week counted equal
    # to a full one.
    assert (900.0 + 1000.0) / 2 == 950.0 != pytest.approx(got, abs=0.01)


# ── like-for-like weeks ──────────────────────────────────────────────────────

def test_a_part_year_is_compared_on_the_same_week_count():
    rows = [(f"2025-{m:02d}-07", 50_000, 850.0 + m, 30_000, 800.0 + m) for m in range(1, 13)]
    rows += [(f"2026-{m:02d}-07", 50_000, 900.0, 30_000, 850.0) for m in range(1, 7)]
    w = fe.fed_weekly(pd.concat([_weekly([r]) for r in rows], ignore_index=True))
    now = fe.ytd(w, 2026)
    like = fe.ytd(w, 2025, weeks=now["weeks"])
    full = fe.ytd(w, 2025)
    assert now["weeks"] == 6 and like["weeks"] == 6 and full["weeks"] == 12
    # The baseline year rises through the year here, so taking the whole of it
    # understates the gain. Both numbers are plausible; only one is a comparison.
    assert like["fed_carcass_lb"] < full["fed_carcass_lb"]


def test_a_baseline_shorter_than_the_window_returns_none_not_a_short_year():
    rows = [("2025-01-07", 50_000, 850.0, 30_000, 800.0)]
    rows += [(f"2026-{m:02d}-07", 50_000, 900.0, 30_000, 850.0) for m in range(1, 7)]
    w = fe.fed_weekly(pd.concat([_weekly([r]) for r in rows], ignore_index=True))
    assert fe.ytd(w, 2025, weeks=6) is None


def test_a_part_year_is_kept_out_of_the_annual_history():
    rows = [(f"2025-{i:02d}-07", 50_000, 900.0, 30_000, 850.0) for i in range(1, 13)]
    w = fe.fed_weekly(pd.concat([_weekly([r]) for r in rows], ignore_index=True))
    assert fe.annual_from_weekly(w) == {}   # 12 weeks is not a year


# ── fed means steers and heifers ─────────────────────────────────────────────

def test_cows_and_bulls_never_reach_the_fed_carcass():
    df = _weekly([("2026-01-03", 60_000, 950.0, 40_000, 870.0)])
    for cls, head, wt in (("COWS", 20_000, 658.0), ("BULLS", 2_000, 917.0),
                          ("GE 500 LBS", 122_000, 870.0)):
        df = pd.concat([df, pd.DataFrame([
            {"week_ending": "2026-01-03", "class_desc": cls, "unit_desc": "HEAD",
             "Value": head},
            {"week_ending": "2026-01-03", "class_desc": cls,
             "unit_desc": "LB / HEAD, DRESSED BASIS", "Value": wt}])], ignore_index=True)
    w = fe.fed_weekly(df)
    assert float(w["fed_head"].iloc[0]) == 100_000
    assert float(w["fed_carcass_lb"].iloc[0]) == pytest.approx(918.0)


def test_the_module_names_only_the_fed_classes():
    assert fe.FED_CLASSES == ("STEERS", "HEIFERS")
    assert "GE 500 LBS" not in MOD_SRC.split('"""', 2)[2]


def test_a_week_missing_a_class_is_dropped_not_half_counted():
    df = _weekly([("2026-01-03", 60_000, 950.0, 40_000, 870.0)])
    df = df[~((df.class_desc == "HEIFERS") & (df.unit_desc == "HEAD"))]
    assert fe.fed_weekly(df).empty


# ── the stock/flow trap ──────────────────────────────────────────────────────

def test_beef_over_on_feed_inventory_cancels_the_weight_gain():
    """The reason on-feed inventory is not a denominator, as arithmetic.

    Real figures: 2015 marketings 19.66M on 10.63M head on feed carrying
    23.46bn lb of beef; 2025 20.46M on 11.82M carrying 25.68bn.
    """
    beef15, mk15, cof15 = 23.46e9, 19.66e6, 10.63e6
    beef25, mk25, cof25 = 25.68e9, 20.46e6, 11.82e6
    turns = fe.turnover(mk25, cof25) / fe.turnover(mk15, cof15) - 1
    weight = fe.per_marketed_head(beef25, mk25) / fe.per_marketed_head(beef15, mk15) - 1
    assert turns < -0.05 and weight > 0.04          # they pull opposite ways
    naive = (beef25 / cof25) / (beef15 / cof15) - 1  # what the stock ratio says
    assert naive == pytest.approx(0.0, abs=0.03)     # ~nothing happened
    assert weight > 0.04                             # the flow ratio sees it


def test_the_module_never_divides_beef_by_an_inventory():
    """`turnover` may touch on-feed; nothing computing a beef ratio may."""
    tree = ast.parse(MOD_SRC)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("per_marketed_head", "head_equivalent"):
        src = ast.get_source_segment(MOD_SRC, fns[name]) or ""
        assert "on_feed" not in src and "inventory" not in src.lower().split('"""')[-1]
    assert "on_feed_jan1" in (ast.get_source_segment(MOD_SRC, fns["turnover"]) or "")


def test_the_offset_share_divides_head_by_head_not_percent_by_percent():
    """The live 2026-vs-2019 figures, which is where this was caught."""
    head_now, head_base = 17_833_600, 21_060_000
    equiv = fe.head_equivalent(head_now, 944.2, 847.6)
    got = fe.offset_share(equiv, head_now, head_base)
    assert round(got) == 63
    # Dividing the two headline percentages instead -- "+11.4% a head" over
    # "-15.3% head" -- lands in the mid-70s. Same question in words, different
    # bases, eleven points apart, and neither answer looks wrong. That form
    # shipped and was caught by reading the rendered tile, not by the suite.
    pct_per_head = 944.2 / 847.6 - 1
    pct_head = 1 - head_now / head_base
    wrong = pct_per_head / pct_head * 100
    assert 74 <= wrong <= 75
    assert wrong - got > 10


def test_the_offset_share_is_beef_over_beef():
    """Scaling both sides by the baseline carcass must not move it."""
    head_now, head_base, base_wt = 17_833_600, 21_060_000, 847.6
    equiv = fe.head_equivalent(head_now, 944.2, base_wt)
    beef_added = equiv * base_wt
    beef_lost = (head_base - head_now) * base_wt
    assert fe.offset_share(equiv, head_now, head_base) == pytest.approx(
        beef_added / beef_lost * 100)


def test_the_offset_share_is_not_capped_at_a_hundred():
    """Over 100% is the headline result, not an overflow to clip."""
    got = fe.offset_share(fe.head_equivalent(19_000_000, 944.2, 847.6),
                          19_000_000, 20_000_000)
    assert got > 100


def test_a_kill_that_did_not_shrink_has_nothing_to_give_back():
    assert fe.offset_share(500_000, 21_000_000, 20_000_000) is None
    assert fe.offset_share(500_000, 20_000_000, 20_000_000) is None


def test_per_marketed_head_is_not_labelled_a_carcass_weight():
    doc = fe.per_marketed_head.__doc__
    assert "NOT A CARCASS WEIGHT" in doc
    # The gap is real and large: fed beef counts every FI steer and heifer,
    # marketings only 1,000+ feedlots.
    assert fe.per_marketed_head(21.96e9, 20.46e6) == pytest.approx(1073, abs=2)


# ── the frozen/live seam ─────────────────────────────────────────────────────

def test_the_frozen_history_stops_where_the_live_window_starts():
    frozen, live_from = fe.load_history()
    assert max(frozen) == live_from - 1
    assert sorted(frozen) == list(range(min(frozen), max(frozen) + 1))  # no gaps


def _full_year(year):
    weeks = pd.date_range(f"{year}-01-05", periods=52, freq="7D").strftime("%Y-%m-%d")
    return fe.fed_weekly(pd.concat(
        [_weekly([(d, 50_000, 900.0, 30_000, 850.0)]) for d in weeks], ignore_index=True))


def test_a_frozen_year_inside_the_live_window_raises():
    """A JSON built with a different LIVE_FROM than the page believes."""
    with pytest.raises(ValueError, match="2019"):
        fe.annual_history(_full_year(2019),
                          {2019: {"fed_head": 1, "fed_carcass_lb": 1.0}}, 2019)


def test_a_complete_live_year_before_the_window_raises():
    """The ETL's window widening backwards under a frozen file nobody rebuilt."""
    with pytest.raises(ValueError, match="2018"):
        fe.annual_history(_full_year(2018), {}, 2019)


def test_the_overlap_guard_accepts_the_shipped_arrangement():
    """A guard that cannot fail is the thing it guards against."""
    frozen, live_from = fe.load_history()
    hist = fe.annual_history(_full_year(live_from), frozen, live_from)
    assert min(hist) == min(frozen) and live_from in hist


def test_aggregating_live_weekly_reproduces_usdas_own_annual_figure():
    """The only place the two sources can be checked against each other.

    `check_years` is NASS's published annual fed figure for years the page
    reads live. It exists for this test alone -- see the build script.
    """
    raw = json.loads((APP / "data" / "fed_equivalent.json").read_text(encoding="utf-8"))
    check = {int(y): v for y, v in raw["check_years"].items()}
    assert check and min(check) == raw["live_from"]
    # Weekly rows reconstructed from the published class figures must roll back
    # up to the published head-weighted carcass weight.
    for year, v in check.items():
        head = v["steer_head"] + v["heifer_head"]
        beef = (v["steer_head"] * v["steer_carcass_lb"]
                + v["heifer_head"] * v["heifer_carcass_lb"])
        assert beef / head == pytest.approx(v["fed_carcass_lb"], abs=0.01)
        assert head == v["fed_head"]


def test_the_page_never_reads_the_check_block():
    assert "check_years" not in PAGE_SRC
    assert "check_years" not in MOD_SRC


# ── baselines ────────────────────────────────────────────────────────────────

def test_only_live_window_years_are_offered_as_a_part_year_baseline():
    frozen, live_from = fe.load_history()
    hist = {**{y: {} for y in frozen}, **{y: {} for y in range(live_from, 2026)}}
    got = fe.baseline_years(hist, live_from, 2026)
    assert got == list(range(live_from, 2026))
    assert not [y for y in got if y < live_from]   # 2015 cannot be like-for-like


def test_every_offered_baseline_year_is_described():
    """A bare year implies one baseline is canonical. Each gets a reason."""
    for year, note in fe.BASELINE_NOTES.items():
        assert note and not note[0].isupper()


# ── the two cattle-on-feed series spell their period differently ─────────────

def _cof_calls():
    """Every `_cof_national(short_desc, period)` call in the page, as literals."""
    out = []
    for node in ast.walk(PAGE_AST):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_cof_national" and len(node.args) == 2):
            a, b = node.args
            if isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
                out.append((a.value, b.value))
    return dict(out)


def test_the_inventory_asks_for_first_of_jan_and_marketings_for_year():
    """Asking the inventory for 'JAN' matches zero rows and renders nothing.

    One is a stock at an instant ('FIRST OF JAN'), the other a flow over a
    period ('YEAR'). Making them agree returns an empty dict and the whole
    turnover panel vanishes from the page with no error anywhere -- which is
    exactly what shipped and was caught in a browser.
    """
    calls = _cof_calls()
    assert calls["CATTLE, ON FEED - INVENTORY"] == "FIRST OF JAN"
    assert (calls["CATTLE, ON FEED - SALES FOR SLAUGHTER, MEASURED IN HEAD"]
            == "YEAR")


def test_a_filter_that_matches_nothing_raises_instead_of_returning_empty():
    """An outage and a wrong filter look identical on the page; only one is a bug."""
    src = PAGE_SRC[PAGE_SRC.index("def _cof_national"):]
    src = src[:src.index("\n@st.cache_data")]
    assert "raise ValueError" in src and "raise KeyError" in src
    # ...and the no-rows-at-all case still returns quietly.
    assert "if not rows:\n        return {}" in src


def test_the_page_says_so_when_the_turnover_panel_is_skipped():
    assert "the turnover panel below the chart is not shown" in PAGE_SRC


# ── the comparison names its own rule ────────────────────────────────────────

def _render_src():
    fn = next(n for n in ast.walk(PAGE_AST)
              if isinstance(n, ast.FunctionDef) and n.name == "_render_cattle_equivalent")
    return ast.get_source_segment(PAGE_SRC, fn) or ""


def test_the_comparison_rule_is_stated_above_the_tiles():
    """"To date" reads as year-over-year; this baseline is a choice.

    Read off the AST rather than the raw text: an f-string split across
    adjacent literals is one node to Python and invisible to a grep, which is
    the mistake this repo records for the placement-records caveat.
    """
    # PAGE_AST, not a re-parse of the extracted function: ast.get_source_segment
    # resolves node offsets against the text that was parsed, so re-parsing a
    # slice and then reading segments out of the whole file returns garbage.
    captions = [seg for n in ast.walk(PAGE_AST)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "caption"
                for seg in [ast.get_source_segment(PAGE_SRC, n) or ""]
                if "How this comparison works" in seg]
    assert len(captions) == 1, "the comparison rule is stated once, or not at all"
    caption = captions[0]
    # it must name BOTH sides and say the weeks are matched
    assert "{current}" in caption and "{baseline}" in caption
    assert "{thru}" in caption and "{base_thru}" in caption
    assert "same number of" in caption and "weeks" in caption
    # and correct the year-over-year assumption outright
    assert "not automatically" in caption and "last year" in caption


def test_the_rule_is_stated_before_the_first_tile():
    """Below the tiles it explains a number the reader has already misread."""
    src = _render_src()
    assert src.index("How this comparison works") < src.index("_eq_tile(")


def test_the_caption_interpolates_the_dates_rather_than_typing_them():
    """A typed date goes stale the week after it is written."""
    src = _render_src()
    i = src.index("How this comparison works")
    block = src[i:i + 700]
    assert not re.search(r"\b20\d\d\b", block), "a literal year in the rule caption"


# ── no network, and the schema key ───────────────────────────────────────────

def test_the_module_acquires_no_http_path():
    tree = ast.parse(MOD_SRC)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"requests", "urllib", "http", "socket", "snowflake"}


def test_schema_is_passed_at_the_call_site_not_left_on_a_default():
    """A default is never hashed into a st.cache_data key -- both halves matter."""
    for node in ast.walk(PAGE_AST):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "_fetch_fed_equivalent":
            assert node.args or node.keywords, "_fetch_fed_equivalent() must be passed SCHEMA"
            return
    pytest.fail("no call to _fetch_fed_equivalent in the page")
