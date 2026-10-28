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
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parent.parent
_APP = _ROOT / "apps" / "cattle_on_feed" / "app.py"
_PR = _ROOT / "apps" / "cattle_on_feed" / "placement_records.py"
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


def _panel_text() -> str:
    """The panel's prose, with implicit string concatenation joined up.

    A caption written as several adjacent literals is ONE sentence to the
    reader and several to a naive grep: "not causes" split across a line break
    reads as absent, and a test that greps the raw source for it fails on
    correct code. Found exactly that way.
    """
    # NO REGEX, AND NO ESCAPES. Python folds implicit concatenation at
    # parse time -- adjacent plain strings become one Constant, adjacent
    # f-strings one JoinedStr -- so the whole sentence is already joined
    # in the tree. Reading it there also avoids the backslash mangling
    # this repo records twice.
    parts = []
    for node in ast.walk(ast.parse(_panel_src())):
        if isinstance(node, ast.JoinedStr):
            parts.append("".join(
                v.value if isinstance(v, ast.Constant)
                and isinstance(v.value, str) else " {} "
                for v in node.values))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            parts.append(node.value)
    return chr(10).join(parts).lower()


# Phrases that assert a CAUSE rather than report a measurement.
_CAUSAL = ("caused by", "driven by", "because of", "due to", "proves",
           "demonstrates", "shows that", "means that", "explains")


def test_the_panel_asserts_no_CAUSE():
    """The standing rule, and it survives the panel gaining a correlation:
    what is banned is a causal CLAIM, not a subject."""
    low = _panel_text()
    for word in _CAUSAL:
        assert word not in low, f"the panel asserts a cause: {word!r}"


def _retention_is_qualified(panel_text: str) -> bool:
    """If the panel talks about retention it must show its working."""
    if not any(w in panel_text for w in
               ("retention", "retaining", "rebuild", "expansion")):
        return True
    return ("r = " in panel_text
            and "not causes" in panel_text
            and "measured" in panel_text)


def test_retention_may_be_MEASURED_but_never_asserted():
    """Ross asked how the per-cow figure might correlate to retention. The
    answer is a number -- about -0.19 against the next year's herd change,
    which is close to nothing -- so the panel reports correlations and names
    them as associations. What it must never do is state the link as fact,
    which is why a mention has to arrive with an r, the word measured, and the
    "not causes" caveat."""
    assert _retention_is_qualified(_panel_text())


def test_the_retention_check_rejects_a_bare_causal_claim():
    """A guard that cannot fail is the thing it guards against."""
    assert not _retention_is_qualified(
        "placements per cow are low, so heifer retention is under way")
    assert _retention_is_qualified("no mention of the subject at all")
    assert _retention_is_qualified(
        "retention: r = -0.19, measured over 30 years, associations not causes")


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


# ── a ranking that does not name its period ──────────────────────────────────

# Phrases that rank this panel's figure against the rest of the series. Each
# one is meaningless without the span it ranks within.
_RANK_MARKERS = ("rolling 12-month windows", "series high", "in any 12 months")


def _rankings_name_their_period(panel: str) -> bool:
    """Does every ranking phrase sit in a tile that also names the span?

    THE FOOT DOES NOT COUNT, and that is not fussiness -- the first version of
    this check was per-CALL, and a tile whose rank line had lost its span still
    passed because the small print underneath happened to mention the year.
    Verified by mutation: it let `{n} rolling 12-month windows` through bare.
    The span has to be on the ranking line or beside it, not in the footnote.
    """
    tree = ast.parse(panel)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_snap_card"):
            continue
        parts = [ast.get_source_segment(panel, a) or "" for a in node.args]
        parts += [ast.get_source_segment(panel, k.value) or ""
                  for k in node.keywords if k.arg != "foot"]
        scope = " | ".join(parts)
        if any(m in scope for m in _RANK_MARKERS) and "_first" not in scope:
            return False
    return True


def test_every_ranking_names_the_span_it_ranks_within():
    """Ross, on the shipped version: *"does 'a series high' mean the most since
    the cattle on feed series began in 1996?"* It did, and the tile never said
    so -- nor did "most on file", nor "the lowest of 358 windows".

    A tile is read on its own and screenshotted away from the caption under
    it, so the span cannot live in that caption. This is the portal's standing
    headline rule arriving on a ranking rather than on a unit.
    """
    assert _rankings_name_their_period(_panel_src())


def test_the_period_check_rejects_the_bare_rankings_it_replaced():
    """A guard that cannot fail is the thing it guards against."""
    bare = ('_snap_card("Placements", "1", "head",\n'
            '    f\'<span>{rank} of {n} rolling 12-month windows</span>\',\n'
            '    \'<span>a series high</span>\')\n')
    assert not _rankings_name_their_period(bare)
    fixed = bare.replace("windows</span>", "windows since {_first}</span>")
    assert _rankings_name_their_period(fixed)
    # And the hole the first version of this check had: a span sitting only in
    # the footnote does NOT rescue a bare ranking line.
    footnoted = ("_snap_card('Placements', '1', 'head',"
                 " f'<span>{rank} of {n} rolling 12-month windows</span>',"
                 " '<span>a series high</span>',"
                 " foot=f'since {_first}')")
    assert not _rankings_name_their_period(footnoted)


def test_the_series_start_comes_from_the_data_not_a_literal():
    """1996 is a property of what NASS serves, not a constant to type in. A
    hard-coded year goes on reading 1996 the day the loaded window moves."""
    src = _panel_src()
    assert '_first = int(_pc["first_year"])' in src
    # STRING CONSTANTS, not the raw source -- a comment quoting Ross's own
    # question mentions the year, and that is not something the page renders.
    # Parsing drops comments for free.
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "1996" not in node.value, f"year written out: {node.value!r}"


# ── where the run in progress stands ─────────────────────────────────────────

def _long_base(years=range(2000, 2016)):
    """Sixteen flat years, so later months can set records under min_prior=10."""
    return [(y, m, 2_000_000) for y in years for m in range(1, 13)]


def test_the_run_in_progress_is_not_one_of_its_own_precedents():
    """`runs()` returns the live run like any other, so counting runs of the
    longest length without excluding it reports the run as matching ITSELF --
    'matched once before' on a run that is the first of its length."""
    rows = _long_base()
    rows += [(2016, 1, 1_000_000), (2016, 2, 1_000_000)]      # a 2-run, live
    st = pr.run_standing(pr.flag_records(_series(rows), min_prior=10))
    assert st == {"current": 2, "longest": 2, "ties": 0, "is_longest": True}


def test_ties_counts_only_EARLIER_runs_of_the_same_length():
    """The shipped case: two runs of three, one of them still running."""
    rows = _long_base()
    rows += [(2016, m, 1_000_000) for m in (1, 2, 3)]          # run of 3
    rows += [(2016, m, 9_000_000) for m in (4, 5)]             # broken
    rows += [(2016, m, 1_000_000) for m in (6, 7, 8)]          # run of 3, live
    st = pr.run_standing(pr.flag_records(_series(rows), min_prior=10))
    assert st["current"] == 3 and st["longest"] == 3
    assert st["ties"] == 1, "the earlier run of three, not itself"
    assert st["is_longest"]


def test_a_shorter_live_run_is_not_the_longest():
    rows = _long_base()
    rows += [(2016, m, 1_000_000) for m in (1, 2, 3)]
    rows += [(2016, 4, 9_000_000)]
    rows += [(2016, 5, 1_000_000)]                             # live run of 1
    st = pr.run_standing(pr.flag_records(_series(rows), min_prior=10))
    assert st["current"] == 1 and st["longest"] == 3
    assert not st["is_longest"]


def test_no_live_run_still_reports_the_longest():
    rows = _long_base()
    rows += [(2016, m, 1_000_000) for m in (1, 2)]
    rows += [(2016, 3, 9_000_000)]                             # newest is not one
    st = pr.run_standing(pr.flag_records(_series(rows), min_prior=10))
    assert st["current"] == 0 and st["longest"] == 2 and not st["is_longest"]


def test_compare_carries_the_standing_to_the_page():
    rows = _long_base()
    rows += [(2016, m, 1_000_000) for m in (1, 2, 3)]
    got = pr.compare(_series(rows), pd.Series({y: 30e6 for y in range(2000, 2017)}),
                     pd.DataFrame(columns=["year", "month", "pct"]))
    assert got["standing"]["current"] == 3


def test_every_branch_of_the_standing_sentence_names_the_span():
    """"the longest on record" ranks against a period it does not state --
    the exact defect Ross reported on the other three tiles. A bare string
    returned from any branch puts it straight back."""
    fn = next(n for n in _tree().body
              if isinstance(n, ast.FunctionDef) and n.name == "_prec_standing")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert returns, "no branches found -- the test is pointed at the wrong name"
    for r in returns:
        src = ast.unparse(r)
        assert isinstance(r.value, ast.JoinedStr), f"bare string returned: {src}"
        names = {n.id for n in ast.walk(r.value) if isinstance(n, ast.Name)}
        assert "first" in names, f"branch does not name the span: {src}"


# ── the ten lowest 12-month totals ───────────────────────────────────────────

def _ramp(years, start=3_000_000, step=-10_000):
    """A series falling steadily, so the newest windows are the lowest."""
    out, v = [], start
    for y in years:
        for m in range(1, 13):
            out.append((y, m, v))
            v += step
    return out


def test_rank_one_is_the_lowest_window():
    got = pr.lowest_windows(_series(_ramp(range(2000, 2011))), n=10)
    assert got["rows"][0]["rank"] == 1
    totals = [r["total"] for r in got["rows"]]
    assert totals == sorted(totals), "rows must run lowest first"
    assert totals[0] == min(totals)


def test_it_returns_at_most_n_and_copes_with_a_short_series():
    rows = _ramp(range(2000, 2002))            # 24 months -> 13 windows
    assert len(pr.lowest_windows(_series(rows), n=10)["rows"]) == 10
    short = _ramp(range(2000, 2001))           # 12 months -> 1 window
    got = pr.lowest_windows(_series(short), n=10)
    assert len(got["rows"]) == 1 and got["of"] == 1


def test_overlapping_windows_are_counted_as_ONE_stretch():
    """The whole reason the caption exists. A steadily falling series puts the
    ten lowest windows on ten CONSECUTIVE month-ends -- one quiet stretch read
    ten times, not ten episodes."""
    got = pr.lowest_windows(_series(_ramp(range(2000, 2011))), n=10)
    assert got["stretches"] == 1


def test_two_separate_quiet_spells_count_as_two_stretches():
    rows = [(y, m, 3_000_000) for y in range(2000, 2012) for m in range(1, 13)]
    rows = dict(((y, m), v) for y, m, v in rows)
    for m in range(1, 13):                      # a quiet 2003
        rows[(2003, m)] = 1_000_000
    for m in range(1, 13):                      # and a quiet 2009
        rows[(2009, m)] = 1_000_000
    p = _series([(y, m, v) for (y, m), v in rows.items()])
    got = pr.lowest_windows(p, n=4)
    assert got["stretches"] == 2, got


def test_per_cow_on_a_row_matches_what_the_tile_reports():
    """The table and the tile above it must not disagree about one window --
    the failure this file records four times over. They agree only because
    both read the same series through the same arithmetic, so that is pinned
    rather than trusted."""
    rows = _ramp(range(2000, 2011))
    cows = pd.Series({y: 30e6 + (y - 2000) * 1e5 for y in range(2000, 2011)})
    p = _series(rows)
    tile = pr.per_cow(p, cows)                  # the newest window
    table = pr.lowest_windows(p, cows, n=10)
    newest = max(table["rows"], key=lambda r: (r["year"], r["month"]))
    assert (newest["year"], newest["month"]) == tile["ends"]
    assert newest["per100"] == pytest.approx(tile["value"])


def test_no_cow_series_leaves_the_column_empty_rather_than_guessing():
    got = pr.lowest_windows(_series(_ramp(range(2000, 2011))), None, n=3)
    assert all(r["per100"] is None for r in got["rows"])


def test_compare_carries_the_ranking_to_the_page():
    rows = _ramp(range(2000, 2011))
    got = pr.compare(_series(rows),
                     pd.Series({y: 30e6 for y in range(2000, 2011)}),
                     pd.DataFrame(columns=["year", "month", "pct"]))
    assert got["lowest_windows"]["rows"][0]["rank"] == 1


def test_the_page_tells_the_reader_the_windows_overlap():
    """Ten rows read as ten episodes. On this series they are three stretches,
    so without the caption the panel overstates how often its own headline
    figure has been reached."""
    src = _panel_src()
    i = src.index("lowest_windows")
    tail = src[i:]
    assert "overlap" in tail
    assert "_low['stretches']" in tail or '_low["stretches"]' in tail, \
        "the number of stretches must be computed, not written down"


# ── one window per year ──────────────────────────────────────────────────────

def test_per_year_returns_one_row_per_calendar_year():
    got = pr.lowest_windows(_series(_ramp(range(2000, 2011))), n=10, per_year=True)
    years = [r["year"] for r in got["rows"]]
    assert len(years) == len(set(years)), "a year may appear once"


def test_per_year_picks_that_years_QUIETEST_window():
    rows = [(y, m, 3_000_000) for y in range(2000, 2004) for m in range(1, 13)]
    rows = {(y, m): v for y, m, v in rows}
    rows[(2002, 5)] = 100_000                   # one very quiet month in 2002
    p = _series([(y, m, v) for (y, m), v in rows.items()])
    got = pr.lowest_windows(p, n=5, per_year=True)
    top = got["rows"][0]
    # The lowest window of 2002 is the first one that CONTAINS that month.
    assert top["year"] == 2002 and top["month"] == 5


def test_per_year_does_NOT_abolish_overlap_and_does_not_claim_to():
    """A December window and the following January window are different years
    and still share eleven months. The caption leans on `stretches` to say so,
    so `stretches` has to keep counting in this mode."""
    rows = {(y, m): 3_000_000 for y in range(2000, 2004) for m in range(1, 13)}
    rows[(2001, 12)] = 100_000                  # drags Dec 2001 AND Jan 2002 down
    p = _series([(y, m, v) for (y, m), v in rows.items()])
    got = pr.lowest_windows(p, n=2, per_year=True)
    ends = sorted((r["year"], r["month"]) for r in got["rows"])
    assert ends == [(2001, 12), (2002, 1)], ends
    assert got["stretches"] == 1, "adjacent month-ends are one stretch"


def test_compare_carries_both_rankings():
    rows = _ramp(range(2000, 2011))
    got = pr.compare(_series(rows), pd.Series({y: 30e6 for y in range(2000, 2011)}),
                     pd.DataFrame(columns=["year", "month", "pct"]))
    assert got["lowest_windows"]["per_year"] is False
    assert got["lowest_per_year"]["per_year"] is True
    ys = [r["year"] for r in got["lowest_per_year"]["rows"]]
    assert len(ys) == len(set(ys))


def test_the_page_offers_both_rankings_and_never_rebinds_view():
    """`view` is bound to a segmented control at module level on this page --
    the collision that cost a rename once already."""
    src = _panel_src()
    assert "lowest_per_year" in src and "segmented_control" in src
    assert "\n        view = " not in src and "\n            view = " not in src


# ── what "per 100 beef cows" means ───────────────────────────────────────────

def test_the_per_cow_column_says_what_it_IS_not_just_what_it_is_made_of():
    """Ross: *"what does the per 100 beef cows mean?"* The column named the
    ratio and the caption named its ingredients; neither said what the number
    counts. A reader who cannot take a normalised figure apart will not trust
    it -- the reasoning that keeps the crush pages' explainers."""
    src = _panel_src()
    assert "for every 100 beef cows" in src, "the caption must define the ratio"
    assert "breeding herd" in src
    i = src.index("Per 100 beef cows\": st.column_config")
    assert "help=" in src[i:i + 400], "the column needs its own tooltip"


def test_tied_totals_rank_by_the_EARLIER_window_not_by_pandas():
    """A RANK column must not depend on incidental ordering. Two windows on
    the same total were being swapped by nsmallest, which would move a row's
    rank between runs with nothing in the data having changed."""
    rows = {(y, m): 3_000_000 for y in range(2000, 2004) for m in range(1, 13)}
    rows[(2002, 5)] = 100_000          # ties the 2002 and 2003 best windows
    p = _series([(y, m, v) for (y, m), v in rows.items()])
    got = pr.lowest_windows(p, n=5, per_year=True)
    assert got["rows"][0]["total"] == got["rows"][1]["total"], "the tie is the point"
    assert (got["rows"][0]["year"], got["rows"][0]["month"]) == (2002, 5)
    assert (got["rows"][1]["year"], got["rows"][1]["month"]) == (2003, 1)
    # and it is stable across repeated calls
    again = pr.lowest_windows(p, n=5, per_year=True)
    assert [(r["year"], r["month"]) for r in again["rows"]] == \
           [(r["year"], r["month"]) for r in got["rows"]]


def test_a_flat_series_yields_no_correlation_rather_than_nan():
    """corr() on a series with no variance returns NaN, and a caption
    interpolating it prints "r = nan" to a client. None drops the sentence."""
    rows = _ramp(range(2000, 2012))
    cows = pd.Series({y: 30e6 for y in range(2000, 2012)})     # herd never moves
    share = pd.DataFrame({"year": list(range(2000, 2012)),
                          "month": [1] * 12, "pct": [35.0] * 12})
    got = pr.retention_signal(_series(rows), cows, share)
    for k in ("per_cow_vs_share", "per_cow_vs_herd", "share_vs_herd"):
        assert got[k] is None or isinstance(got[k], float)
        if got[k] is not None:
            assert got[k] == got[k], f"{k} is NaN"


def test_retention_signal_measures_what_it_claims_on_a_known_relationship():
    """A herd that falls hardest after the years with the most placed per cow
    must come back NEGATIVE, or the sign convention is wrong and every word of
    the caption is backwards."""
    years = list(range(2000, 2016))
    rows, cows = [], {}
    for i, y in enumerate(years):
        hot = i % 2 == 0                      # alternate heavy / light years
        for m in range(1, 13):
            rows.append((y, m, 2_500_000 if hot else 1_500_000))
        cows[y] = 30e6
    # herd shrinks the year AFTER a heavy year
    for i, y in enumerate(years[1:], 1):
        cows[y] = cows[years[i - 1]] * (0.97 if (i - 1) % 2 == 0 else 1.03)
    got = pr.retention_signal(_series(rows), pd.Series(cows),
                              pd.DataFrame(columns=["year", "month", "pct"]))
    assert got["per_cow_vs_herd"] is not None
    assert got["per_cow_vs_herd"] < 0, got["per_cow_vs_herd"]


# ── a stock is not a flow ────────────────────────────────────────────────────

def test_on_feed_is_AVERAGED_not_summed():
    """Placements are a flow and twelve months of them add up. Cattle on feed
    is a standing count: summing it bills the same animal for every month it
    stands in the yard. The wrong one still produces a plausible number — 132
    million head reads as a big year, not as a category error."""
    rows = [(y, m, 11_000_000) for y in (2000, 2001) for m in range(1, 13)]
    flow = pr.lowest_windows(_series(rows), n=1)
    stock = pr.lowest_windows(_series(rows), n=1, agg="mean")
    assert flow["rows"][0]["total"] == pytest.approx(132_000_000)
    assert stock["rows"][0]["total"] == pytest.approx(11_000_000)
    assert stock["agg"] == "mean" and flow["agg"] == "sum"


def test_a_duplicated_month_is_REFUSED_rather_than_quietly_rescaled():
    """rolling(12) counts ROWS, not calendar months. A frame carrying two
    capacity classes gives a "12-month" window spanning six months — hit for
    real on the on-feed cache, which holds fifteen classes under one
    short_desc and ranked Jan 1997 twice at 2.5M against a true 11M."""
    rows = [(2000, m, 1_000_000) for m in range(1, 13)]
    rows += [(2000, 6, 9_000_000)]                     # June twice
    with pytest.raises(ValueError, match="duplicated month"):
        pr.lowest_windows(_series(rows), n=1)


def test_the_duplicate_guard_names_the_offending_month():
    rows = [(2000, m, 1_000_000) for m in range(1, 13)] + [(2000, 6, 5.0)]
    try:
        pr.lowest_windows(_series(rows), n=1)
    except ValueError as e:
        assert "2000-06" in str(e), str(e)
    else:
        raise AssertionError("no refusal")


def test_the_page_averages_the_on_feed_series():
    """The page must ask for the mean. Passing the default would rank sums of
    an inventory, which is the category error above with nothing raising."""
    src = _panel_src()
    assert "lowest_onfeed" in src
    mod = ast.parse(_PR.read_text(encoding="utf-8"))
    comp = next(n for n in mod.body
                if isinstance(n, ast.FunctionDef) and n.name == "compare")
    calls = [c for c in ast.walk(comp)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id == "lowest_windows"]
    onfeed = [c for c in calls
              if any(k.arg == "agg" and k.value.value == "mean" for k in c.keywords)]
    assert len(onfeed) == 2, "both on-feed rankings must average"


# ── the two chart bases ──────────────────────────────────────────────────────

def test_both_bases_cover_the_SAME_windows():
    """The switch changes the normalisation and nothing else. Different
    windows under one heifer line would put three series on one x-axis
    describing different twelve-month spans, which no caption can repair."""
    rows = _ramp(range(2000, 2011))
    cows = pd.Series({y: 30e6 for y in range(2000, 2011)})
    p = _series(rows)
    assert set(pr.total_by_year(p)) == set(pr.per_cow(p, cows)["by_year"])


def test_the_total_series_agrees_with_the_ranking_table():
    """Two surfaces, one figure: the bar for the newest year and rank 1 of the
    any-window table are the same window, so they must be the same number."""
    rows = _ramp(range(2000, 2011))
    p = _series(rows)
    tot = pr.total_by_year(p)
    low = pr.lowest_windows(p, n=1)
    newest = max(tot)
    assert low["rows"][0]["year"] == newest
    assert tot[newest] == pytest.approx(low["rows"][0]["total"])


def test_total_by_year_takes_the_LAST_window_of_each_year():
    rows = [(y, m, 1_000_000) for y in (2000, 2001) for m in range(1, 13)]
    rows += [(2002, m, 1_000_000 if m < 12 else 5_000_000) for m in range(1, 13)]
    got = pr.total_by_year(_series(rows))
    assert got[2002] == pytest.approx(11 * 1_000_000 + 5_000_000), \
        "December's window, not January's"


def test_the_chart_is_fed_one_series_and_a_matching_label():
    """A y-axis title naming per-cow over a bar of raw head, or the reverse,
    is the silent failure here -- both render perfectly."""
    src = _panel_src()
    i = src.index("prec_basis_chart(")
    call = src[i:i + 500]
    assert "_tot_by_year if _is_total else _pc_by_year" in call
    assert "Head placed, 12 months" in call and "per 100 beef cows" in call
    # the label and the hover must switch on the SAME condition as the data
    assert call.count("_is_total") == 3, call


def test_the_total_basis_is_a_sum_not_an_average():
    """Placements are a flow. The on-feed ranking averages; this must not."""
    rows = [(y, m, 1_000_000) for y in (2000, 2001) for m in range(1, 13)]
    assert pr.total_by_year(_series(rows))[2001] == pytest.approx(12_000_000)


# ── heifers on feed, on every ranking ────────────────────────────────────────

def test_the_heifer_series_is_bound_BEFORE_every_use():
    """Streamlit runs the page top to bottom. The heifer series was bound down
    in the chart section, below the placements table that now reads it — which
    is a NameError on the live page that py_compile, the suite and
    get_page_text all pass. This page has hit that twice; it is a line-number
    check for that reason, not a style preference."""
    src = _panel_src()
    assign = src.index("_heif = _pc.get(")
    uses = [i for i in range(len(src))
            if src.startswith("_heif.get(", i) or src.startswith("_heif,", i)]
    assert uses, "nothing reads the heifer series"
    assert assign < min(uses), "the heifer series is used before it is bound"


def test_both_rankings_show_heifers_on_feed():
    """Ross wanted the heifer figures beside whichever years reach the top
    ten, on the placements table as well as the on-feed one."""
    src = _panel_src()
    # plain substrings: the headings are split across string literals, so a
    # probe carrying the opening quote matches nothing.
    pl = src.index("ten lowest 12-month placement")
    of = src.index("ten lowest 12-month average")
    for name, start, end in (("placements", pl, of), ("on-feed", of, len(src))):
        block = src[start:end]
        assert '"Heifers on feed"' in block, f"{name} table has no heifer column"
        assert '"Heifer share percentile"' in block, name
        # the COLUMN NAME alone is satisfied by the column_config entry, so
        # assert the table actually READS the series too. Caught by mutation:
        # renaming the row key left the config behind and the test passed.
        assert "_heif.get(" in block or "_heif.get" in block,             f"{name} table names the column but never reads the series"


def test_both_tables_read_ONE_heifer_source():
    """Two tables computing the percentile two ways would both be defensible
    and would disagree — the failure this file records five times."""
    src = _panel_src()
    assert src.count("_pc.get(\"heifer_by_year\"") == 1
    assert "share_at(" not in src, "the page must not recompute the percentile"


# ── the heifer-share contrast ────────────────────────────────────────────────

def _heif_map(pairs):
    return {y: {"pct": p, "percentile": q} for y, p, q in pairs}


def test_the_spread_reports_both_ENDS_of_the_ranking():
    rows = [{"year": 2015}, {"year": 2016}, {"year": 2026}]
    got = pr.heifer_spread(rows, _heif_map([(2015, 32.6, 4), (2016, 32.9, 6),
                                            (2026, 37.8, 54)]))
    assert got["low"]["year"] == 2015 and got["low"]["percentile"] == 4
    assert got["high"]["year"] == 2026 and got["high"]["percentile"] == 54
    assert got["gap"] == pytest.approx(50) and got["material"]


def test_a_narrow_spread_is_not_worth_a_sentence():
    """"from the 48th to the 52nd" is noise wearing the clothes of a finding."""
    rows = [{"year": 2020}, {"year": 2021}]
    got = pr.heifer_spread(rows, _heif_map([(2020, 37.0, 48), (2021, 37.4, 52)]))
    assert not got["material"], got


def test_the_threshold_is_the_shipped_one():
    assert pr.HEIFER_SPREAD_MATERIAL == 20


def test_a_ranking_with_one_known_year_has_no_spread():
    got = pr.heifer_spread([{"year": 2026}, {"year": 1900}],
                           _heif_map([(2026, 37.8, 54)]))
    assert got == {}


def test_the_caption_reads_BOTH_ENDS_at_render_time():
    """Writing "4th" and "54th" into the sentence is how a caption comes to
    disagree with the table printed directly above it. Both ends move as USDA
    revises and as new windows enter the ranking."""
    src = _panel_src()
    tree = ast.parse(_APP.read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_prec_spread_line")
    body = ast.unparse(fn)
    assert "heifer_spread(" in body
    assert "percentile" in body
    # RENDERED STRINGS ONLY, never the docstring -- it quotes Ross's request,
    # which names the very numbers the sentence must not hard-code. Dropping
    # the first statement is how the docstring leaves the comparison.
    rendered = []
    for node in ast.walk(ast.Module(body=fn.body[1:], type_ignores=[])):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            rendered.append(node.value)
    blob = " ".join(rendered)
    for literal in ("4th", "54th", "32.6", "37.8"):
        assert literal not in blob, f"{literal!r} written into the sentence"
    assert "_prec_spread_line(" in src, "the caption must call it"


def test_the_spread_sentence_asserts_no_cause():
    fn = next(n for n in ast.parse(_APP.read_text(encoding="utf-8-sig")).body
              if isinstance(n, ast.FunctionDef) and n.name == "_prec_spread_line")
    low = ast.unparse(fn).lower()
    for word in _CAUSAL:
        assert word not in low, f"the spread sentence asserts a cause: {word!r}"


def test_a_tied_percentile_names_the_more_extreme_share():
    """Percentiles print rounded, so two years can both read "4th" and differ
    underneath. Picking on float order alone named 2016 at 32.9% while the
    table above showed 2015 at 32.6% on the same printed percentile."""
    rows = [{"year": 2015}, {"year": 2016}, {"year": 2026}]
    got = pr.heifer_spread(rows, _heif_map([(2015, 32.6, 4), (2016, 32.9, 4),
                                            (2026, 37.8, 54)]))
    assert got["low"]["year"] == 2015, "the lower share wins the tie"
    assert got["low"]["pct"] == pytest.approx(32.6)
