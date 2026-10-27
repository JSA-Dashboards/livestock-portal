"""The Placement Records panel, and the rule that decides what it concludes.

Ross asked how the current run of record-low placement months compares with the
2014-15 rebuild. The first answer was WRONG, and it was wrong because of one
parameter, which is why most of this file is about that parameter.

**A SHORT HISTORY MANUFACTURES RECORDS.** A calendar month cannot set a record
the first time it appears, and barely can the second. Requiring 5 prior years
admits Sep-Nov 2001 -- which is not a low-placement episode at all: its lowest
"record" month is 7.4% ABOVE the highest month of the 2026 run, and its
12-month total ranks 302nd of 359. Admitting it makes record runs look routine
and reverses the comparison. Requiring 10 leaves exactly two runs in thirty
years, 2015 and 2026.

The other three things pinned here:
  * records are judged AT THE TIME, not against years that had not happened
  * the 12-month total is seasonality-free by construction, and the panel says
    so rather than claiming an adjustment it does not make
  * **the panel attributes no cause.** Whether this is heifer retention or a
    smaller herd is the reader's call; this page has a standing rule against a
    caption that supplies a plausible wrong one, and the first pass at this
    analysis is exactly why.

    python -m pytest tests/test_placement_records.py -q
"""

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parent.parent
_APP = _ROOT / "apps" / "cattle_on_feed" / "app.py"
sys.path.insert(0, str(_ROOT / "apps" / "cattle_on_feed"))

import placement_records as pr  # noqa: E402


def _series(rows):
    """[(year, month, value)] -> the frame the module takes."""
    return pd.DataFrame(rows, columns=["year", "month", "Value"])


def _flat(years, value=2_000_000, months=(1,)):
    return _series([(y, m, value) for y in years for m in months])


# ── the rule that decides the answer ─────────────────────────────────────────

def test_a_month_cannot_set_a_record_before_there_is_anything_to_beat():
    """The first appearance of a calendar month is a record by construction."""
    p = _series([(2000, 7, 1_000_000)])
    assert not pr.flag_records(p, min_prior=0).record.any()


def test_a_short_history_manufactures_records_and_min_prior_stops_it():
    """Three prior years then a dip. With a low bar that is a 'record'; with
    the shipped bar it is simply a low month, which is what 2001 was."""
    rows = [(y, 7, 2_000_000) for y in range(1996, 1999)] + [(1999, 7, 1_900_000)]
    p = _series(rows)
    assert pr.flag_records(p, min_prior=2).record.iloc[-1] is True or \
           bool(pr.flag_records(p, min_prior=2).record.iloc[-1])
    assert not bool(pr.flag_records(p, min_prior=10).record.iloc[-1])


def test_the_shipped_minimum_is_ten_and_it_is_deliberate():
    assert pr.MIN_PRIOR_YEARS == 10


def test_records_are_judged_at_the_time_not_against_the_future():
    """2,000 then 1,900 then 1,800: the middle month WAS a record when it
    printed. Comparing against the whole series retrospectively erases it."""
    p = _series([(2000, 7, 2_000_000), (2001, 7, 1_900_000), (2002, 7, 1_800_000)])
    f = pr.flag_records(p, min_prior=1)
    assert list(f.record) == [False, True, True]


def test_a_record_needs_to_be_strictly_lower():
    """Equalling the previous low is not beating it."""
    p = _series([(2000, 7, 2_000_000), (2001, 7, 2_000_000)])
    assert not pr.flag_records(p, min_prior=1).record.iloc[-1]


# ── runs ─────────────────────────────────────────────────────────────────────

def test_runs_are_consecutive_months_and_a_gap_splits_them():
    rows = [(y, m, 2_000_000) for y in range(2000, 2016) for m in range(1, 13)]
    rows += [(2016, 1, 1_000_000), (2016, 2, 1_000_000),
             (2016, 3, 9_000_000), (2016, 4, 1_000_000)]
    out = pr.runs(pr.flag_records(_series(rows), min_prior=10), min_run=2)
    assert len(out) == 1 and out[0]["months"] == 2
    assert out[0]["start"] == (2016, 1) and out[0]["end"] == (2016, 2)


def test_current_run_counts_back_from_the_newest_month_only():
    rows = [(y, m, 2_000_000) for y in range(2000, 2016) for m in range(1, 13)]
    rows += [(2016, 1, 1_000_000), (2016, 2, 9_000_000), (2016, 3, 1_000_000)]
    f = pr.flag_records(_series(rows), min_prior=10)
    assert pr.current_run(f) == 1          # Feb broke it; only Mar counts


def test_a_newest_month_that_is_not_a_record_gives_zero():
    rows = [(y, m, 2_000_000) for y in range(2000, 2016) for m in range(1, 13)]
    rows += [(2016, 1, 1_000_000), (2016, 2, 9_000_000)]
    assert pr.current_run(pr.flag_records(_series(rows), min_prior=10)) == 0


# ── the seasonality-free framing ─────────────────────────────────────────────

def test_the_rolling_window_holds_every_calendar_month_exactly_once():
    """This is the whole reason it needs no seasonal adjustment, and the panel
    says so -- so it has to be true."""
    rows = [(y, m, 1_000 * m) for y in (2000, 2001, 2002) for m in range(1, 13)]
    p = _series(rows).sort_values(["year", "month"])
    got = pr.rolling_total(p)
    assert got["window"] == 12
    assert got["total"] == sum(1_000 * m for m in range(1, 13))


def test_the_rolling_rank_counts_strictly_lower_windows():
    rows = [(y, m, 1_000_000) for y in (2000, 2001) for m in range(1, 13)]
    rows += [(2002, m, 500_000) for m in range(1, 13)]
    got = pr.rolling_total(_series(rows))
    assert got["rank"] == 1, "the newest window is the lowest, so rank 1"


# ── the discriminator ────────────────────────────────────────────────────────

def test_per_cow_falls_when_placements_fall_against_a_steady_herd():
    rows = [(y, m, 1_000_000) for y in (2000, 2001) for m in range(1, 13)]
    rows += [(2002, m, 500_000) for m in range(1, 13)]
    cows = pd.Series({2000: 30e6, 2001: 30e6, 2002: 30e6})
    assert pr.per_cow(_series(rows), cows)["rank"] == 1


def test_per_cow_is_FLAT_when_the_herd_shrinks_with_the_placements():
    """The case the panel exists to expose: placements at a record low purely
    because there are fewer cattle. Per cow, nothing has happened."""
    rows = [(y, m, 1_000_000) for y in (2000, 2001) for m in range(1, 13)]
    rows += [(2002, m, 500_000) for m in range(1, 13)]
    cows = pd.Series({2000: 30e6, 2001: 30e6, 2002: 15e6})   # herd halved too
    got = pr.per_cow(_series(rows), cows)
    before = pr.per_cow(_series(rows[:24]), cows)["value"]
    # THE VALUE is the claim, not the rank. Halving both leaves per-cow exactly
    # where it was, so it TIES the earlier window -- and rank counts strictly
    # lower windows, which makes a tie rank 1. Asserting rank > 1 here fails
    # against correct behaviour, which is what the first version of this test
    # did.
    assert got["value"] == pytest.approx(before), "per cow, nothing happened"
    raw = pr.rolling_total(_series(rows))
    assert raw["rank"] == 1, "while the RAW total is a record -- the whole point"


def test_per_cow_skips_years_with_no_cow_figure_rather_than_guessing():
    rows = [(y, m, 1_000_000) for y in (2000, 2001, 2002) for m in range(1, 13)]
    got = pr.per_cow(_series(rows), pd.Series({2000: 30e6}))
    assert got and got["of"] >= 1


# ── how the page uses it ─────────────────────────────────────────────────────

def _tree():
    return ast.parse(_APP.read_text(encoding="utf-8-sig"))


def _panel_src():
    src = _APP.read_text(encoding="utf-8-sig")
    i = src.index("\nwith tab_prec:")
    j = src.index("\nwith tab_season:", i)
    return src[i:j]


def test_the_panel_attributes_no_cause():
    """The standing rule. Whether this is retention or a smaller herd is what
    the three figures let a reader judge; the page must not decide it."""
    low = _panel_src().lower()
    for word in ("retention", "retaining", "rebuild", "expansion", "because of"):
        assert word not in low, f"the panel asserts a cause: {word!r}"


def test_the_panel_names_the_record_rule_it_used():
    """A record is only meaningful against its rule, and the rule is a
    judgement -- so it is printed rather than buried in the module."""
    src = _panel_src()
    assert "min_prior" in src
    assert "calendar month" in src


def test_the_panel_warns_that_imported_steers_sit_in_the_denominator():
    """The correction that reversed the first analysis. Without it the heifer
    share reads mechanically high in any year imports are blocked."""
    low = _panel_src().lower()
    assert "steers" in low and "denominator" in low


def test_the_beef_cow_fetch_filters_to_SURVEY():
    """CENSUS rows land in 1997, 2002 and 2017 at ~1.4M against a true ~30M,
    on a series used here as a denominator."""
    fn = next(n for n in _tree().body
              if isinstance(n, ast.FunctionDef) and n.name == "fetch_beef_cows")
    assert "'SURVEY'" in ast.dump(fn) or '"SURVEY"' in ast.unparse(fn)


def test_the_beef_cow_params_are_the_exact_cache_key():
    """us_cow_herd's BEEF_COWS omits the four BASE keys every other fetch on
    this page sends. The cache key is a hash of the exact dict, so adding them
    returns nothing at all."""
    fn = next(n for n in _tree().body
              if isinstance(n, ast.FunctionDef) and n.name == "fetch_beef_cows")
    call = next(n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "fetch_cached")
    keys = {k.value for k in call.args[0].keys}
    assert keys == {"agg_level_desc", "short_desc"}, keys


def test_the_fetch_is_cached_on_the_module_schema():
    """The cache serves shape, not freshness -- the leverage.SCHEMA trap. It
    must be PASSED, because a default is not part of the key."""
    fn = next(n for n in _tree().body
              if isinstance(n, ast.FunctionDef) and n.name == "fetch_beef_cows")
    assert any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
               and d.func.attr == "cache_data" for d in fn.decorator_list)
    assert "placement_records.SCHEMA" in _panel_src()


def test_the_panel_body_is_guarded_by_the_lazy_tab():
    """A hidden Streamlit tab is hidden, not skipped -- the body would run on
    every load of every other tab, and on the client app too."""
    src = _panel_src()
    assert "if tab_prec.open:" in src


def test_the_panel_sits_at_module_level_not_inside_cold_storage():
    """render_cold_storage() has its OWN tab_season, and splicing a
    module-level block against the unanchored text put this inside it."""
    src = _APP.read_text(encoding="utf-8-sig")
    assert "\nwith tab_prec:" in src
    assert "\n    with tab_prec:" not in src


# ── the row that would not stay level ────────────────────────────────────────

def _is_one_grid(src: str) -> bool:
    """Does this panel lay its tiles out as a single CSS grid?"""
    flat = src.replace(" ", "")
    return ("st.columns" not in src
            and "prec-grid" in src
            and "grid-template-columns:repeat(4,1fr)" in flat
            and ".prec-grid>.snap-card{height:100%" in flat)


def test_the_tiles_are_one_grid_not_four_streamlit_columns():
    """The four feet wrap to different line counts, and as st.columns that
    left the row ragged at 192/206/233/233px -- which py_compile, the suite
    and get_page_text all pass, exactly as the daily cash tile row did.

    IT CANNOT BE FIXED FROM OUTSIDE THE COLUMNS. Five wrappers sit between the
    column and the card, and `height: 100%` on the column is WORSE than
    nothing: an explicit height defeats the flex row's own
    `align-items: stretch`, then resolves against an auto-height parent, so
    the column comes out SHORTER than the row it is in. Measured in a browser,
    not reasoned about. Grid items stretch to their row by default.
    """
    assert _is_one_grid(_panel_src())


def test_the_grid_check_rejects_the_columns_form_it_replaced():
    """A guard that cannot fail is the thing it guards against."""
    broken = ('with st.container(key="prec_tiles"):\n'
              '    c1, c2, c3, c4 = st.columns(4)\n'
              'with c1:\n'
              '    st.markdown(_snap_card("x", "1", "y"), unsafe_allow_html=True)\n')
    assert not _is_one_grid(broken)


def test_the_tiles_skip_the_markdown_parser():
    """Four tiles of USDA figures in one block is where a pair of dollar signs
    becomes inline LaTeX -- which has shipped on this portal twice."""
    src = _panel_src()
    i = src.index("prec-grid")
    assert "st.html(" in src[:i], "the grid must be emitted through st.html"
