"""USDA's released text written over the cached QuickStats history.

The Cattle on Feed page had two halves on two clocks: the COF Recap parses
USDA's released report text and has the new month within minutes, while every
other tab waited on QuickStats and then on the cache job behind it. On
2026-10-23 that gap was a full day and read as a broken dashboard.

The overlay closes it. Four things here would be wrong silently:

  * **The month offset.** The October report carries the OCTOBER 1 inventory
    but SEPTEMBER placements, marketings and other disappearance. Give the
    flows the inventory's offset and every flow figure lands a month late — on
    a page where a month-late placement number is entirely plausible.
  * **The units.** The tables print "1,000 head"; QuickStats serves head. An
    un-multiplied overlay is out by a factor of a thousand.
  * **Append instead of replace.** The prior month is usually already cached,
    so concatenating leaves TWO rows for it and every downstream .max() and
    groupby picks between them at random.
  * **Two fetches of the release.** The recap and the overlay must describe the
    same report. Two cache entries expiring independently is the original bug
    one level down.

    python -m pytest tests/test_cof_release_overlay.py -q
"""

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parent.parent
_APP = _ROOT / "apps" / "cattle_on_feed" / "app.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(_ROOT / "apps" / "cattle_on_feed"))

import cof_recap  # noqa: E402
from streamlit_source import load_from_app  # noqa: E402

_NS = load_from_app(_APP, "overlay_released", "series_for",
                    consts=("STATE_NAMES", "_STATE_BY_NAME"),
                    globals_={"pd": pd})
overlay_released = _NS["overlay_released"]

# A cut-down October 2026 release: the two tables whose offsets differ, with
# their real headers, so the parser is exercised on the shape USDA prints.
RELEASE = """
Cattle on Feed Inventory on 1,000+ Capacity Feedlots by Month - States and United States:
2025 and 2026
------------------------------------------------------------------------------
                  :                 :                 :   October 1, 2026
       State      : October 1, 2025 :September 1, 2026:   Inventory   : Percent
------------------------------------------------------------------------------
                  :     --------------- 1,000 head --------------
Iowa .............:        690               670              680           99            101
United States ....:     11,418            11,168           11,372          100            102
------------------------------------------------------------------------------

Cattle Marketed on 1,000+ Capacity Feedlots by Month - States and United States:
2025 and 2026
------------------------------------------------------------------------------
                  :    During    :    During    :      During September 2026
       State      :September 2025: August 2026  :  Marketings  : Percent
------------------------------------------------------------------------------
                  :    ------------ 1,000 head -----------
Iowa .............:       74             59             68            92            115
United States ....:    1,632          1,517          1,524            93            100
------------------------------------------------------------------------------

Cattle on Feed by Class on 1,000+ Capacity Feedlots by Quarter - States and United States:
2025 and 2026
------------------------------------------------------------------------------
                    :       Steers and steer calves        :      Heifers and heifer calves
        State       :   Oct 1,   :   Jul 1,   :   Oct 1,   :   Oct 1,   :   Jul 1,   :   Oct 1,
                    :    2025    :    2026    :    2026    :    2025    :    2026    :    2026
------------------------------------------------------------------------------
                    :                                 1,000 Head
Iowa ...............:     550          540          540          140          140          140
United States ......:   7,063        7,120        7,072        4,355        4,250        4,300
------------------------------------------------------------------------------
"""


def _rows():
    return cof_recap.released_rows(RELEASE, 2026, 10)


def _one(series, state, year, month):
    hits = [r for r in _rows() if r["series"] == series
            and r["state_name"] == state and (r["year"], r["month"]) == (year, month)]
    assert len(hits) == 1, f"{series}/{state} {month}/{year}: {len(hits)} rows"
    return hits[0]["value"]


# ── the offsets, which are the whole correctness ─────────────────────────────

def test_inventory_is_dated_the_report_month():
    """October's report carries the October 1 inventory."""
    assert _one("inventory", "United States", 2026, 10) == 11_372_000
    assert _one("inventory", "United States", 2026, 9) == 11_168_000    # restated
    assert _one("inventory", "United States", 2025, 10) == 11_418_000   # year ago


def test_the_flows_are_dated_the_month_BEFORE_the_report():
    """October's report carries SEPTEMBER marketings. Dating these October is
    the mistake that renders perfectly."""
    assert _one("marketings", "United States", 2026, 9) == 1_524_000
    assert _one("marketings", "United States", 2026, 8) == 1_517_000
    assert _one("marketings", "United States", 2025, 9) == 1_632_000
    assert not [r for r in _rows()
                if r["series"] == "marketings" and (r["year"], r["month"]) == (2026, 10)]


def test_the_offsets_differ_between_the_two_kinds_of_table():
    """If these ever coincide, one of them is wrong."""
    assert cof_recap.RELEASED_TABLES["inventory"][1] == 0
    for flow in ("placements", "marketings", "other"):
        assert cof_recap.RELEASED_TABLES[flow][1] == -1


@pytest.mark.parametrize("y,m,delta,expect", [
    (2026, 10, -1, (2026, 9)), (2026, 1, -1, (2025, 12)),
    (2026, 1, -12, (2025, 1)), (2026, 12, 1, (2027, 1)),
])
def test_month_shift_rolls_the_year(y, m, delta, expect):
    assert cof_recap._shift(y, m, delta) == expect


# ── the quarterly class split ────────────────────────────────────────────────

def test_the_class_split_steps_back_a_QUARTER_not_a_month():
    """Its header reads "Oct 1, 2025 | Jul 1, 2026 | Oct 1, 2026" per class.

    Reuse the monthly -1 and July's figure is filed under September — a quarter
    the series has never had a value for, so a real number lands on a date USDA
    never published and the chart simply grows a point.
    """
    assert _one("heifers", "United States", 2026, 10) == 4_300_000
    assert _one("heifers", "United States", 2026, 7) == 4_250_000     # prior QUARTER
    assert _one("heifers", "United States", 2025, 10) == 4_355_000
    assert not [r for r in _rows()
                if r["series"] == "heifers" and (r["year"], r["month"]) == (2026, 9)]


def test_steers_and_heifers_read_their_own_halves_of_the_row():
    """Six columns: steers for three periods, then heifers for the same three.
    Off-by-three here swaps the two classes and the share inverts."""
    assert _one("steers", "United States", 2026, 10) == 7_072_000
    assert _one("heifers", "United States", 2026, 10) == 4_300_000
    assert _one("steers", "Iowa", 2026, 10) == 540_000
    assert _one("heifers", "Iowa", 2026, 10) == 140_000


@pytest.mark.parametrize("state", ["United States", "Iowa"])
@pytest.mark.parametrize("period", [(2026, 10), (2025, 10)])
def test_steers_plus_heifers_equals_the_inventory(state, period):
    """USDA's own free audit, and the reason a column slip cannot hide: the
    class split must reconcile to the headline inventory for the same date."""
    y, m = period
    assert (_one("steers", state, y, m) + _one("heifers", state, y, m)
            == _one("inventory", state, y, m))


def test_a_non_quarterly_report_yields_no_class_rows():
    """Eight reports a year carry no class table at all. No month test does
    this -- the table is simply absent and _table_block finds nothing."""
    monthly_only = RELEASE[:RELEASE.index("Cattle on Feed by Class")]
    rows = cof_recap.released_rows(monthly_only, 2026, 11)
    assert not [r for r in rows if r["series"] in ("steers", "heifers")]
    assert [r for r in rows if r["series"] == "inventory"], "the rest must still parse"


def test_the_class_row_shape_is_passed_to_the_table_reader():
    """The six-column row matches neither _STATE_ROW nor _US_ROW, so without
    the explicit shape _table_block returns nothing and the split silently
    never appears."""
    assert cof_recap._table_block(RELEASE, cof_recap._CLASS_TABLE) == []
    assert cof_recap._table_block(RELEASE, cof_recap._CLASS_TABLE,
                                  cof_recap._CLASS_ROW)


def test_no_compiled_pattern_carries_a_literal_backspace():
    """A heredoc turned \\b into a backspace in this repo once; re compiles it
    silently and the pattern then matches nothing at all."""
    import re as _re
    for name in dir(cof_recap):
        v = getattr(cof_recap, name)
        if isinstance(v, _re.Pattern):
            assert "\x08" not in v.pattern, name


# ── units and naming ─────────────────────────────────────────────────────────

def test_values_are_head_not_thousands():
    """The tables say "1,000 head"; QuickStats serves head."""
    assert _one("inventory", "Iowa", 2026, 10) == 680_000


def test_state_names_come_back_as_printed():
    """app.py owns STATE_NAMES; a second copy in cof_recap is the
    snowflake_db-times-five problem in miniature."""
    names = {r["state_name"] for r in _rows()}
    assert "United States" in names and "Iowa" in names
    assert not any(len(n) == 2 and n.isupper() for n in names)


def test_every_name_the_release_prints_is_mappable():
    """An unmapped name is silently dropped, so the page would keep the stale
    figure for that state and nothing would say so."""
    real = cof_recap.released_rows(
        (Path(__file__).parent / "fixtures" / "cof_release_1026.txt").read_text(encoding="utf-8"),
        2026, 10) if (Path(__file__).parent / "fixtures" / "cof_release_1026.txt").exists() else _rows()
    unmapped = {r["state_name"] for r in real
                if r["state_name"].lower() not in _NS["_STATE_BY_NAME"]}
    assert not unmapped, f"unmapped: {sorted(unmapped)}"


# ── the overlay itself ───────────────────────────────────────────────────────

def _frame(rows):
    return pd.DataFrame([
        {"year": y, "month": m, "date": pd.Timestamp(year=y, month=m, day=1),
         "agg_level_desc": "NATIONAL", "state_alpha": "US", "Value": float(v)}
        for y, m, v in rows])


def test_the_release_replaces_rather_than_appends():
    """The prior month is usually already cached. Two rows for one month is
    the failure nothing downstream reports."""
    cached = _frame([(2026, 8, 1), (2026, 9, 11_163_000)])
    out = overlay_released(cached, "inventory", _rows())
    assert not out.duplicated(["state_alpha", "year", "month"]).any()
    sep = out[(out.year == 2026) & (out.month == 9) & (out.state_alpha == "US")]
    assert len(sep) == 1 and sep.iloc[0]["Value"] == 11_168_000, "the restatement must win"


def test_months_the_release_does_not_cover_are_untouched():
    cached = _frame([(2024, 5, 999_000), (2026, 9, 11_163_000)])
    out = overlay_released(cached, "inventory", _rows())
    keep = out[(out.year == 2024) & (out.month == 5)]
    assert len(keep) == 1 and keep.iloc[0]["Value"] == 999_000


def test_no_release_leaves_the_frame_exactly_as_it_was():
    """Presentation must never cost the numbers."""
    cached = _frame([(2026, 9, 11_163_000)])
    pd.testing.assert_frame_equal(overlay_released(cached, "inventory", []), cached)


def test_an_empty_frame_is_not_resurrected():
    empty = _frame([]).iloc[0:0]
    assert overlay_released(empty, "inventory", _rows()).empty


# ── how the page wires it ────────────────────────────────────────────────────

def _tree():
    return ast.parse(_APP.read_text(encoding="utf-8-sig"))


def test_the_recap_and_the_overlay_come_from_one_fetch():
    """Two cached fetches of the release can expire apart, and then the Recap
    tab and the Summary tiles show different months -- which is the bug this
    whole change exists to fix, reintroduced one level down."""
    fn = next(n for n in _tree().body
              if isinstance(n, ast.FunctionDef) and n.name == "_latest_recap")
    body = ast.dump(fn)
    assert "'released_rows'" in body, "_latest_recap must build the overlay rows too"
    assert "'latest_report'" in body
    src = _APP.read_text(encoding="utf-8-sig")
    assert src.count("cof_recap.latest_report()") == 1, (
        "the release is fetched in more than one place")


def test_the_overlay_is_applied_outside_load_all_s_cache():
    """load_all holds an hour because it is a Snowflake read; this is a merge
    over ~150 rows. Inside, the new month would wait for the hour too."""
    src = _APP.read_text(encoding="utf-8-sig")
    assert src.index("= load_all(LOAD_YEARS, Q_YEARS)") < src.index("overlay_released(inv,")
    fn = next(n for n in _tree().body
              if isinstance(n, ast.FunctionDef) and n.name == "load_all")
    assert "overlay_released" not in ast.dump(fn)


def test_all_four_monthly_series_are_overlaid():
    src = _APP.read_text(encoding="utf-8-sig")
    for frame, key in (("inv", "inventory"), ("place", "placements"),
                       ("sales", "marketings"), ("other", "other"),
                       ("heifer", "heifers"), ("steer", "steers")):
        assert f'overlay_released({frame}, ' in src.replace("  ", " ") or \
               f'overlay_released({frame},' in src, f"{frame} not overlaid"
        assert f'"{key}"' in src
