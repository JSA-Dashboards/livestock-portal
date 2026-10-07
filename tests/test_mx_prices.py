"""Proof that the Mexico-vs-border comparison cannot quietly become dishonest.

Every assertion here is a way the panel could print a plausible, wrong number
without raising: a calf matched to the wrong weight bracket, a heifer priced
against a steer quote, a sale restated by a later move in the peso, a per-head
lot divided by a weight nobody stated. None of those look wrong on a tile.

    python -m pytest tests/test_mx_prices.py -q
"""

import ast
import os
import sys
from datetime import date

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "mexican_feeder_imports")
sys.path.insert(0, _APP)
sys.path.insert(0, os.path.join(_HERE, "..", "scripts"))

import mx_prices as mxp  # noqa: E402

MODULE = os.path.join(_APP, "mx_prices.py")


# ── the page must not acquire an HTTP path ──────────────────────────────────

def test_the_page_module_cannot_fetch():
    """CLAUDE.md's rule for this page: border.py has no `requests` so the
    Streamlit process cannot acquire one, and the ingest lives elsewhere.

    Asserted by AST rather than grep, because this module's own docstring
    explains the rule and says the word -- the mistake tests/test_rundown.py
    made first time and records.
    """
    tree = ast.parse(open(MODULE, encoding="utf-8").read())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    for banned in ("requests", "urllib", "httpx", "mx_auction"):
        assert banned not in imported, f"mx_prices imports {banned}"


def test_the_conversion_matches_the_scraper_exactly():
    """mx_prices copies usd_per_cwt rather than importing it, because the
    scraper needs `requests` and the page may not have one. A copy is only safe
    while something compares the two; this is that something.
    """
    mx_auction = pytest.importorskip("mx_auction")
    assert mxp.LB_PER_KG == mx_auction.LB_PER_KG
    for kg in (43.0, 69.32, 75.38, 90.0, 110.13, 0.01):
        for fx in (17.1382, 18.1259, 25.0):
            assert mxp.usd_per_cwt(kg, fx) == mx_auction.usd_per_cwt(kg, fx)
    assert mxp.usd_per_cwt(None, 18.0) is None
    assert mxp.usd_per_cwt(75.0, None) is None
    assert mxp.usd_per_cwt(75.0, 0) is None, "a zero rate must not divide"


def test_the_conversion_is_right_against_a_hand_figure():
    """75.38 MXN/kg at 18.1259 MXN/USD is $188.64/cwt, checked by hand:
    75.38 / 2.2046 = 34.19 MXN/lb; / 18.1259 = 1.8864 USD/lb; x 100."""
    assert mxp.usd_per_cwt(75.38, 18.1259) == pytest.approx(188.64, abs=0.01)


# ── weight matching, the one judgement call ─────────────────────────────────

def test_an_open_band_has_no_midpoint():
    """"menor a 150kg" has no low end. Treating the missing end as zero puts a
    150 kg calf at 75 kg and matches it four rungs down the ladder."""
    assert mxp.band_midpoint_lb(None, 150) is None
    assert mxp.band_midpoint_lb(301, None) is None
    assert mxp.band_midpoint_lb(301, 350) == pytest.approx(717.6, abs=0.1)


US = [(400.0, 500.0, 415.0), (500.0, 600.0, 385.0),
      (600.0, 700.0, 345.0), (700.0, 800.0, 315.0)]


def test_a_band_above_every_bracket_matches_nothing():
    """351-400 kg is 774-882 lb and AMS stops at 800. Snapping it to 700-800
    would compare a heavier calf to a lighter quote and report the weight slide
    as a price gap -- a number that moves the right way for the wrong reason.
    """
    mid = mxp.band_midpoint_lb(351, 400)
    assert mid > 800
    assert mxp.match_us_band(mid, US) is None


def test_a_band_below_every_bracket_matches_nothing():
    assert mxp.match_us_band(mxp.band_midpoint_lb(151, 180), US) is None


def test_the_heaviest_matched_band_lands_in_700_800():
    """The page's own border headline is 700-800 lb, so the comparison's
    headline has to be the band that lands there or the two panels quote
    different brackets at each other."""
    got = mxp.match_us_band(mxp.band_midpoint_lb(301, 350), US)
    assert got == (700.0, 800.0, 315.0)


def test_two_mexican_bands_may_share_one_bracket():
    """181-200 and 201-230 kg both sit inside 400-500 lb. They are kept as
    separate rows; averaging them with no head counts would print a figure no
    lot ever traded at."""
    a = mxp.match_us_band(mxp.band_midpoint_lb(181, 200), US)
    b = mxp.match_us_band(mxp.band_midpoint_lb(201, 230), US)
    assert a == b == (400.0, 500.0, 415.0)


def test_a_missing_midpoint_never_matches():
    assert mxp.match_us_band(None, US) is None


# ── which rows are even eligible ────────────────────────────────────────────

def test_only_feeder_classes_are_kept():
    for keep in ("BECERRO CN 301-350KG", "BECERRA CN 151-180KG"):
        assert mxp.is_feeder(keep)
    for drop in ("VACA GORDA", "TORO", "TORETE", "NOVILLONAS", "VAQUILLAS",
                 "VACA DELGADA"):
        assert not mxp.is_feeder(drop), f"{drop} is not a feeder calf"


def test_the_wide_cnh_ladder_is_flagged():
    """CNH lots overlap the narrow ladder and run a grade cheaper -- 58.33
    against 81.89 MXN/kg on the 2026-09-30 sale. Comparing both ladders would
    double-count a weight and drag every figure down by a grade difference the
    US quote does not share."""
    assert mxp.is_cnh("BECERRO CNH 251-330")
    assert mxp.is_cnh("BECERRA CNH 130-230KG")
    assert not mxp.is_cnh("BECERRO CN 251-280KG")


def test_sex_maps_to_the_class_that_quotes_the_same_animal():
    assert mxp.US_CLASS_BY_SEX["M"] == "Steers"
    assert mxp.US_CLASS_BY_SEX["F"] == "Spayed Heifers"


# ── the fake Snowflake, for the read paths ──────────────────────────────────

class _Cur:
    def __init__(self, answers):
        self.answers = answers
        self.sql = []
        self._rows = []

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.sql.append((flat, params))
        self._rows = []
        for probe, rows in self.answers.items():
            if probe in flat:
                self._rows = rows(params) if callable(rows) else rows
                break
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def test_fx_reaches_backward_and_never_forward():
    """A sale is priced at the rate that stood when it traded. Reaching forward
    would restate a past sale every time the peso moved -- the decay failure
    the cash forecast tab's analogue cap exists to stop, arriving here by a
    different route.
    """
    cur = _Cur({"FROM JSA.CME_FEEDER_CATTLE.FX_USDMXN":
                [(date(2026, 9, 30), 18.1259)]})
    d, rate = mxp.fx_on(_Conn(cur), date(2026, 9, 30))
    assert (d, rate) == (date(2026, 9, 30), 18.1259)
    sql, params = cur.sql[0]
    assert "RATE_DATE <= %s" in sql, "fx_on must not look forward"
    assert "ORDER BY RATE_DATE DESC" in sql


def test_a_missing_rate_leaves_the_price_empty():
    cur = _Cur({"FROM JSA.CME_FEEDER_CATTLE.FX_USDMXN": []})
    assert mxp.fx_on(_Conn(cur), date(2026, 9, 30)) == (None, None)


def _band_row(cls, sex, lo, hi, avg, unit="MXN/kg"):
    return (cls, sex, lo, hi, avg - 2, avg + 2, avg, unit)


def test_a_per_head_lot_is_never_divided_by_a_weight_nobody_stated():
    """The scraper records the unit it saw. A per-head price turned into a
    per-kilo one needs a weight the sale did not publish, so the cell stays
    empty instead of carrying an invented number."""
    cur = _Cur({f"FROM {mxp.MX_TABLE}": [
        _band_row("BECERRO CN 301-350KG", "M", 301, 350, 75.38),
        _band_row("BECERRO LOTE", "M", 301, 350, 18000.0, "MXN/head"),
    ]})
    rows = mxp.bands(_Conn(cur), date(2026, 9, 30))
    by = {r["clasificacion"]: r for r in rows}
    assert by["BECERRO CN 301-350KG"]["price_avg"] == 75.38
    assert by["BECERRO LOTE"]["price_avg"] is None
    assert by["BECERRO LOTE"]["unit"] == "MXN/head"


def test_non_feeder_rows_never_reach_the_frame():
    cur = _Cur({f"FROM {mxp.MX_TABLE}": [
        _band_row("BECERRO CN 301-350KG", "M", 301, 350, 75.38),
        _band_row("VACA GORDA", "F", None, None, 50.63),
        _band_row("TORO", "M", None, None, 50.50),
    ]})
    rows = mxp.bands(_Conn(cur), date(2026, 9, 30))
    assert [r["clasificacion"] for r in rows] == ["BECERRO CN 301-350KG"]


def test_a_quote_further_away_than_the_limit_is_refused():
    """Beyond MAX_GAP_DAYS the panel shows the sale with no comparison rather
    than a spread measured across a month of market movement."""
    cur = _Cur({"ABS(DATEDIFF":
                [(date(2026, 1, 1), mxp.MAX_GAP_DAYS + 1)]})
    on, bands, gap = mxp.us_bands_near(_Conn(cur), date(2026, 9, 30), "Steers")
    assert (on, bands, gap) == (None, [], None)


def test_a_quote_inside_the_limit_is_taken():
    cur = _Cur({
        "ABS(DATEDIFF": [(date(2026, 9, 30), 0)],
        "SELECT weight_low, weight_high, avg_price":
            [(700, 800, 315.0), (600, 700, 345.0)],
    })
    on, bands, gap = mxp.us_bands_near(_Conn(cur), date(2026, 9, 30), "Steers")
    assert on == date(2026, 9, 30) and gap == 0
    assert (700, 800, 315.0) in bands


def test_the_border_query_pins_class_and_grade():
    """Pairing a Mexican heifer against a steer quote reads as a discount that
    is really a sex difference, and grade 2-3 against 1-2 the same way."""
    cur = _Cur({"ABS(DATEDIFF": [(date(2026, 9, 30), 0)],
                "SELECT weight_low": []})
    mxp.us_bands_near(_Conn(cur), date(2026, 9, 30), "Spayed Heifers")
    sql, params = cur.sql[0]
    assert "class_desc = %s" in sql and "muscle_grade = %s" in sql
    assert params[1] == "Spayed Heifers" and params[2] == mxp.US_GRADE


# ── the headline ────────────────────────────────────────────────────────────

def _cmp(rows):
    return {"rows": rows}


def test_the_headline_takes_the_heaviest_matched_band():
    rows = [
        {"sex": "M", "pct": 57.8, "mid_lb": 420.0},
        {"sex": "M", "pct": 59.9, "mid_lb": 717.6},
        {"sex": "M", "pct": 56.4, "mid_lb": 530.0},
    ]
    assert mxp.headline(_cmp(rows), "M")["mid_lb"] == 717.6


def test_the_headline_ignores_unmatched_and_other_sexes():
    rows = [
        {"sex": "M", "pct": None, "mid_lb": 828.0},   # above every bracket
        {"sex": "F", "pct": 61.0, "mid_lb": 900.0},   # wrong sex
        {"sex": "M", "pct": 59.9, "mid_lb": 717.6},
    ]
    assert mxp.headline(_cmp(rows), "M")["mid_lb"] == 717.6


def test_no_matched_band_yields_no_headline():
    assert mxp.headline(_cmp([{"sex": "M", "pct": None, "mid_lb": 1.0}]),
                        "M") is None
    assert mxp.headline(None, "M") is None


# ── the shape key ───────────────────────────────────────────────────────────

def test_a_schema_key_exists_for_the_cache():
    """st.cache_data keys on the decorated function's code and never on the
    modules it calls, so a new key in compare() would keep serving a dict from
    before it existed and the tiles would render "—" with nothing raising."""
    assert isinstance(mxp.SCHEMA, int)
