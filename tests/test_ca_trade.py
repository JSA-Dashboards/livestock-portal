"""Proof that the US-Canada trade panel cannot quietly report the wrong flow.

Every assertion is a way the panel could print a plausible head count that is
not the one it claims: the World total row summed in with the countries, a
class missing from the identity, a part year beside full ones, a feeder export
figure that does not exist, or a year-ago comparison against twelve months of
one year and eight of another.

    python -m pytest tests/test_ca_trade.py -q
"""

import ast
import io
import os
import sys

import pandas as pd
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "canadian_feeder_cattle")
sys.path.insert(0, _APP)

import ca_trade as ct  # noqa: E402

MODULE = os.path.join(_APP, "ca_trade.py")

HEADER = ('"COMMODITY_DESC","TRADE_FLOW","UNIT_DESC","GEOGRAPHY_CODE",'
          '"GEOGRAPHY_DESC","YEAR_ID","TIMEPERIOD_ID","AMOUNT"\n')


def _csv(rows):
    """rows: (commodity, flow, country, year, month, head)."""
    body = "".join(
        f'"{c}","{f}","Head",1220,"{g}",{y},{m},{h}\n'
        for c, f, g, y, m, h in rows)
    return (HEADER + body).encode("utf-8")


def _canada_year(year, feeder, slaughter, breeding, exports, months=12):
    """A complete year of Canada rows whose classes sum to the total."""
    out = []
    for m in range(1, months + 1):
        out += [
            (ct.FEEDER, ct.IMPORTS, "Canada", year, m, feeder),
            (ct.SLAUGHTER, ct.IMPORTS, "Canada", year, m, slaughter),
            (ct.BREEDING, ct.IMPORTS, "Canada", year, m, breeding),
            (ct.TOTAL, ct.IMPORTS, "Canada", year, m,
             feeder + slaughter + breeding),
            (ct.TOTAL, ct.EXPORTS, "Canada", year, m, exports),
        ]
    return out


# ── the identity that is the only free audit here ───────────────────────────

def test_the_three_import_classes_must_sum_to_usdas_own_total():
    df = ct.parse(_csv(_canada_year(2025, 100, 300, 10, 250)))
    a = ct.reconciles(df)
    assert a["ok"] is True and a["worst"] == 0 and a["checked"] == 12


def test_a_missing_class_is_caught_rather_than_reading_as_a_smaller_market():
    """A class quietly absent from a month looks exactly like less trade, and
    every figure stays a plausible head count. Nothing else here would
    notice."""
    rows = [r for r in _canada_year(2025, 100, 300, 10, 250)
            if not (r[0] == ct.BREEDING and r[4] == 7)]
    a = ct.reconciles(ct.parse(_csv(rows)))
    assert a["ok"] is False
    assert a["worst"] == 10 and a["worst_at"] == (2025, 7)


def test_the_tolerance_is_zero_because_the_identity_is_exact():
    """Integer head counts, one agency, one file. Slack on that is a hole, not
    a safeguard -- the argument leverage.py makes for OI_TOLERANCE."""
    src = open(MODULE, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "reconciles")
    tol = next(d for a, d in zip(fn.args.args[::-1], fn.args.defaults[::-1])
               if a.arg == "tolerance")
    assert isinstance(tol, ast.Constant) and tol.value == 0


# ── World total is a ROW ────────────────────────────────────────────────────

def test_world_total_is_never_summed_into_a_country_figure():
    """The trap trade_flows.py records: summing every GEOGRAPHY_DESC doubles
    the answer, and a doubled cattle import figure is entirely plausible."""
    rows = _canada_year(2025, 100, 300, 10, 250, months=1)
    rows += [(ct.TOTAL, ct.IMPORTS, "World total", 2025, 1, 500)]
    df = ct.parse(_csv(rows))
    got, _ = ct.ytd(df, ct.IMPORTS, ct.TOTAL, 2025)
    assert got == 410, "Canada's own total, not Canada plus the World row"


def test_share_is_taken_against_usdas_world_row_not_a_sum():
    rows = _canada_year(2025, 100, 300, 10, 250, months=1)
    rows += [(ct.TOTAL, ct.IMPORTS, "World total", 2025, 1, 500),
             (ct.TOTAL, ct.IMPORTS, "Mexico", 2025, 1, 90)]
    df = ct.parse(_csv(rows))
    assert ct.share_of_us_imports(df, 2025) == pytest.approx(82.0)


# ── the asymmetry, read off the data ────────────────────────────────────────

def test_the_export_side_carries_no_feeder_class():
    """THE REASON THE PAGE CANNOT SHOW A FEEDER EXPORT FIGURE. Asserted from
    the frame rather than from a docstring, so if ERS ever adds one the page's
    caption stops being true instead of quietly misleading."""
    df = ct.parse(_csv(_canada_year(2025, 100, 300, 10, 250, months=1)))
    assert ct.export_classes(df) == [ct.TOTAL]
    assert ct.series(df, ct.EXPORTS, ct.FEEDER).empty


def test_the_class_floor_is_reported_rather_than_implied():
    """`Cattle, total` runs from 1989 and the classes from 2012. A chart that
    overlays them without saying so makes feeders look like they collapsed to
    zero for twenty-three years."""
    rows = [(ct.TOTAL, ct.IMPORTS, "Canada", 1995, m, 50) for m in range(1, 13)]
    rows += _canada_year(2012, 100, 300, 10, 250)
    df = ct.parse(_csv(rows))
    assert ct.class_floor(df) == 2012
    assert int(df["year"].min()) == 1995


def test_latest_month_reads_the_total_not_the_feeder_class():
    """Reading it off the feeder class would report the file as ending
    wherever the class split ends."""
    rows = [(ct.TOTAL, ct.IMPORTS, "Canada", 2026, m, 50) for m in range(1, 9)]
    rows += [(ct.FEEDER, ct.IMPORTS, "Canada", 2026, m, 10) for m in range(1, 4)]
    assert ct.latest_month(ct.parse(_csv(rows))) == (2026, 8)


# ── part years ──────────────────────────────────────────────────────────────

def test_the_year_in_progress_is_left_off_the_annual_chart():
    """A bar covering eight months beside twelve-month bars is a true number
    telling a false story -- the rule the beef page already enforces."""
    rows = _canada_year(2024, 100, 300, 10, 250)
    rows += _canada_year(2025, 100, 300, 10, 250, months=8)
    df = ct.parse(_csv(rows))
    a = ct.annual(df, ct.IMPORTS, ct.FEEDER)
    assert list(a["year"]) == [2024], "the part year must not be a bar"
    full = ct.annual(df, ct.IMPORTS, ct.FEEDER, complete_only=False)
    assert sorted(full["year"]) == [2024, 2025]
    assert int(full[full["year"] == 2025]["months"].iloc[0]) == 8


def test_a_year_ago_comparison_is_capped_to_the_same_months():
    """Eight months of this year against twelve of last is the part-year error
    wearing a different hat, and it reports a collapse that is a calendar."""
    rows = _canada_year(2024, 100, 300, 10, 250)
    rows += _canada_year(2025, 100, 300, 10, 250, months=8)
    df = ct.parse(_csv(rows))
    now, n = ct.ytd(df, ct.IMPORTS, ct.FEEDER, 2025, through_month=8)
    prv, p = ct.ytd(df, ct.IMPORTS, ct.FEEDER, 2024, through_month=8)
    assert now == prv == 800 and n == p == 8, "same months, so no change"
    uncapped, _ = ct.ytd(df, ct.IMPORTS, ct.FEEDER, 2024)
    assert uncapped == 1200, "uncapped would invent a 33% fall"


def test_a_year_with_no_rows_returns_none_rather_than_zero():
    """Zero head and no data are different answers, and only one of them means
    the trade stopped."""
    df = ct.parse(_csv(_canada_year(2025, 100, 300, 10, 250, months=1)))
    assert ct.ytd(df, ct.IMPORTS, ct.FEEDER, 1999) == (None, 0)
    assert ct.share_of_us_imports(df, 1999) is None


# ── the source, and what it is not ──────────────────────────────────────────

def test_it_reads_ers_and_never_census():
    """Census was probed and rejected on four measured grounds -- exports
    collapse to one Schedule B code, bison contaminates a naive 0102* sum, the
    sub-90kg codes are bob calves at 96-98 lb, and the HS vocabulary breaks at
    2012-01. Asserted by AST so the docstring explaining that cannot satisfy
    it, the trap tests/test_rundown.py records."""
    tree = ast.parse(open(MODULE, encoding="utf-8").read())
    urls = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("http")]
    assert any("ers.usda.gov" in u for u in urls)
    assert not any("census.gov" in u for u in urls)


def test_the_fetch_retries_because_the_cdn_flaps():
    """A single-shot GET reports an outage that is not happening -- the lesson
    paid for on marsapi in the Beef Trimmings work."""
    src = open(MODULE, encoding="utf-8").read()
    assert "status_forcelist" in src and "503" in src


def test_a_csv_missing_a_needed_column_raises_rather_than_rendering_empty():
    bad = b'"TRADE_FLOW","GEOGRAPHY_DESC","YEAR_ID","TIMEPERIOD_ID","AMOUNT"\n'
    with pytest.raises(ValueError) as e:
        ct.parse(bad)
    assert "COMMODITY_DESC" in str(e.value)


def test_a_schema_key_exists_for_the_cache():
    assert isinstance(ct.SCHEMA, int)
