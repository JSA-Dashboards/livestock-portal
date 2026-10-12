"""Proof that the Canadian panel cannot quietly become dishonest.

Every assertion here is a way this panel could print a plausible, wrong number
without raising: a week labelled five days early, a Canadian-dollar price shown
as US, a fortnight of market printed as a week's move, USDA's own YTD rate
silently recomputed from our arithmetic, a Christmas closure reported as a
missing week. None of those look wrong on a tile.

The fixtures copy the SHAPE of AMS 3213 and carry real figures read off the
live feed on 2026-10-07 for the week ending 2026-09-26, so a test that passes
is a test against what USDA actually published.

    python -m pytest tests/test_ca_prices.py -q
"""

import ast
import os
import sys
from datetime import date

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "canadian_feeder_cattle")
sys.path.insert(0, _APP)

import ca_prices as cap  # noqa: E402

MODULE = os.path.join(_APP, "ca_prices.py")


def _price_row(**kw):
    """One AMS 3213 Report Detail Price row, in the feed's own spelling."""
    row = {
        "report_date": "09/21/2026",
        "report_begin_date": "09/20/2026",
        "report_end_date": "09/26/2026",
        "published_date": "10/06/2026 07:06:18",
        "commodity": "Feeder Cattle",
        "country_of_origin": "Canada",
        "region": "Alberta",
        "price_unit": "Per Cwt",
        "currency": "US Dollar",
        "sale_type": None,
        "class": "Steers",
        "quality_grade": None,
        "yield_grade": None,
        "weight_group": "601-700",
        "current_price": 399.45,
    }
    row.update(kw)
    return row


def _slaughter_row(**kw):
    row = {
        "report_date": "09/21/2026",
        "report_begin_date": "09/20/2026",
        "report_end_date": "09/26/2026",
        "published_date": "10/06/2026 07:06:18",
        "commodity": "Livestock Slaughter",
        "cat": "Federally Inspected Slaughter",
        "country_of_origin": "Canada",
        "class": "Cattle",
        "volume_unit": "Head",
        "current_volume": 63175,
        "week_ago_volume": 0,
        "year_ago_volume": 0,
        "current_YTD_volume": 2067700,
        "prior_YTD_volume": 2113947,
        "percent_change": -2.2,
    }
    row.update(kw)
    return row


# ── the page must not acquire an HTTP path ──────────────────────────────────

def test_the_page_module_cannot_fetch():
    """CLAUDE.md's rule for this page: border.py has no `requests` so the
    Streamlit process cannot acquire one, and the ingest lives elsewhere.

    Doubly binding here -- marsapi.ams.usda.gov rejects Community Cloud's IPs,
    so a live fetch from the page would fail in production whatever we wanted.

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
    for banned in ("requests", "urllib", "httpx", "urllib3"):
        assert banned not in imported, f"ca_prices imports {banned}"


def test_it_never_binds_snowflake_db_by_bare_name():
    """snowflake_db.py exists five times and Python caches by NAME, so whichever
    page loads first wins. This module loads it by path under a private name,
    the trick draft_store, sources and am_cutout all use."""
    tree = ast.parse(open(MODULE, encoding="utf-8").read())
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            assert all(a.name != "snowflake_db" for a in n.names), \
                "ca_prices imports snowflake_db by bare name"
        if isinstance(n, ast.ImportFrom):
            assert n.module != "snowflake_db", \
                "ca_prices imports from snowflake_db by bare name"
    assert "_ca_prices_db" in open(MODULE, encoding="utf-8").read()


def test_every_table_is_named_in_full():
    """Nine modules each default SNOWFLAKE_SCHEMA to the schema they own, so an
    unqualified table here would join that collision. CLAUDE.md: unset is the
    only working configuration, and a module that names tables in full takes no
    part in it."""
    for name in (cap.PRICE_TABLE, cap.SLAUGHTER_TABLE):
        assert name.count(".") == 2, f"{name} is not database.schema.table"
        assert name.startswith("JSA."), name
    src = open(MODULE, encoding="utf-8").read()
    assert "SNOWFLAKE_SCHEMA" not in src, "ca_prices reads SNOWFLAKE_SCHEMA"


# ── the week ending ─────────────────────────────────────────────────────────

def test_the_week_ends_on_report_end_date_not_report_date():
    """THE TRAP THIS MODULE EXISTS TO AVOID.

    report_date is the MONDAY of the week covered; the week ends the Saturday
    AFTER it. A tile labelled from report_date is wrong by five days and looks
    entirely plausible -- the hand-typed deck shipped "as of 8/19/26" against a
    week ending 9/19/26 for exactly this reason.
    """
    rows = cap.parse_prices([_price_row()])
    assert rows[0]["week_ending"] == date(2026, 9, 26)
    assert rows[0]["report_date"] == date(2026, 9, 21)
    assert rows[0]["week_ending"] != rows[0]["report_date"]
    assert (rows[0]["week_ending"] - rows[0]["report_date"]).days == 5


def test_a_holiday_shifted_week_is_read_not_derived():
    """31 of 3,499 rows are shifted to Tue/Mon/Sun. Deriving the week ending as
    report_date + 5 would be right 99% of the time, which is the worst possible
    hit rate for a bug nobody can see."""
    rows = cap.parse_prices([_price_row(report_date="09/22/2026",
                                        report_begin_date="09/21/2026",
                                        report_end_date="09/27/2026")])
    assert rows[0]["week_ending"] == date(2026, 9, 27)
    assert (rows[0]["week_ending"] - rows[0]["report_date"]).days == 5


# ── currency ────────────────────────────────────────────────────────────────

def test_a_canadian_dollar_price_is_refused_and_reported():
    """All 3,499 rows read US Dollar today. A Canadian report is exactly where
    that could change, and a CAD price shown as USD is a ~1.35x error that
    renders perfectly and sorts correctly. Refused, and the reason recorded --
    so the panel says "rows rejected" instead of showing a cheap Alberta."""
    rejects = []
    rows = cap.parse_prices([_price_row(currency="Canadian Dollar")], rejects)
    assert rows == []
    assert len(rejects) == 1
    assert "Canadian Dollar" in rejects[0]


def test_a_per_head_price_is_refused():
    """Per Cwt is the only unit this module understands. A per-head lot divided
    by nothing would print as a very cheap hundredweight."""
    rejects = []
    assert cap.parse_prices([_price_row(price_unit="Per Head")], rejects) == []
    assert rejects and "Per Head" in rejects[0]


def test_a_band_that_did_not_trade_is_dropped_but_not_reported_as_a_fault():
    """170 of 2,590 feeder rows carry a null price -- normal. Counting those as
    rejections would bury a real rejection in noise."""
    rejects = []
    assert cap.parse_prices([_price_row(current_price=None)], rejects) == []
    assert rejects == [], "a null price is not a fault"


def test_null_is_never_zero():
    rows = cap.parse_prices([_price_row(current_price=None), _price_row()])
    assert len(rows) == 1
    assert all(r["price"] != 0 for r in rows)


# ── corrections ─────────────────────────────────────────────────────────────

def test_a_correction_supersedes_rather_than_duplicating():
    """Zero duplicates exist today, checked over all 2,590 feeder rows. AMS
    issues corrections, and a correction arrives as a second row with the same
    key and a later published_date -- the shape that would silently double a
    weekly average."""
    original = _price_row(current_price=399.45)
    corrected = _price_row(current_price=401.10, published_date="10/08/2026 07:00:00")
    rows = cap.parse_prices([original, corrected])
    assert len(rows) == 1
    assert rows[0]["price"] == 401.10


# ── the ladder ──────────────────────────────────────────────────────────────

def test_the_ladder_keeps_a_weight_that_did_not_trade():
    """A missing rung reads as a ladder that stops, which is a different
    statement from one that has a hole."""
    rows = cap.parse_prices([
        _price_row(weight_group="501-600", current_price=451.11),
        _price_row(weight_group="601-700", current_price=399.45),
    ])
    ladder = cap.feeder_ladder(rows, "Alberta")
    assert [r["weight_group"] for r in ladder] == list(cap.FEEDER_WEIGHTS)
    assert ladder[1]["Steers"] == 451.11
    assert ladder[0]["Steers"] is None, "401-500 did not trade; it must still appear"


def test_sex_is_kept_separate():
    """Pairing a heifer against a steer quote reads as a discount that is really
    a sex difference -- the rule mx_prices follows for BECERRO/BECERRA."""
    rows = cap.parse_prices([
        _price_row(weight_group="701-800", **{"class": "Steers"}, current_price=364.50),
        _price_row(weight_group="701-800", **{"class": "Heifers"}, current_price=331.14),
    ])
    rung = cap.feeder_ladder(rows, "Alberta")[3]
    assert rung["weight_group"] == "701-800"
    assert rung["Steers"] == 364.50
    assert rung["Heifers"] == 331.14


def test_western_regions_lead_and_ontario_is_not_first():
    """Alberta and Saskatchewan are where cattle bound for the US come from.
    Ontario is an eastern market that mostly does not cross, and a panel led by
    it would be ordered by nothing."""
    assert cap.REGIONS[0] == "Alberta"
    assert cap.WESTERN == ("Alberta", "Saskatchewan")
    assert "Ontario" not in cap.WESTERN


# ── changes ─────────────────────────────────────────────────────────────────

def test_a_week_on_week_change_never_bridges_the_year_end_gap():
    """AMS loses ISO weeks 52 and 1. The previous ROW is then three weeks old,
    and that difference is three weeks of market dressed as one -- it looks
    like an ordinary move and is not. The rule
    letter/sources.fetch_futures follows."""
    rows = cap.parse_prices([
        _price_row(report_end_date="12/20/2025", current_price=380.00,
                   published_date="12/30/2025 07:00:00"),
        _price_row(report_end_date="01/10/2026", current_price=395.00,
                   published_date="01/20/2026 07:00:00"),
    ])
    latest, prior, change = cap.price_change(rows, "Alberta", "Steers", "601-700")
    assert latest == 395.00
    assert prior is None, "the week before ISO 2026-W02 is W01, which AMS did not publish"
    assert change is None, "a bridged change is worse than a missing one"


def test_an_adjacent_week_does_produce_a_change():
    rows = cap.parse_prices([
        _price_row(report_end_date="09/19/2026", current_price=395.00,
                   published_date="09/29/2026 07:00:00"),
        _price_row(report_end_date="09/26/2026", current_price=399.45),
    ])
    latest, prior, change = cap.price_change(rows, "Alberta", "Steers", "601-700")
    assert (latest, prior, change) == (399.45, 395.00, 4.45)


# ── slaughter ───────────────────────────────────────────────────────────────

def test_usda_percent_change_is_reproduced_not_recomputed():
    """USDA's percent_change is its arithmetic over its own revisions.
    Recomputing it from ytd/ytd_prior would produce a table that is neither
    source's -- the rule letter/sterling.py follows for the Sterling tracker.

    Note the fixture's own figures do NOT reconcile to the published -2.2
    exactly (2067700/2113947-1 = -2.188%), which is the point: USDA rounds its
    own way and we print what USDA printed.
    """
    rows = cap.parse_slaughter([_slaughter_row()])
    summary = cap.slaughter_summary(rows, "Cattle")
    assert summary["pct_change"] == -2.2
    assert summary["ytd"] == 2067700
    assert summary["ytd_prior"] == 2113947
    src = open(MODULE, encoding="utf-8").read()
    assert "ytd_prior\"] - 1" not in src and "/ row[\"ytd_prior\"]" not in src


def test_the_weekly_and_ytd_comparisons_are_not_conflated():
    """head vs head_year_ago is a WEEKLY question; pct_change is USDA's YTD
    one. Both look like "percent change" and they are different -- the
    two-clocks error in miniature."""
    rows = cap.parse_slaughter([_slaughter_row(year_ago_volume=65000)])
    s = cap.slaughter_summary(rows, "Cattle")
    assert s["head"] == 63175 and s["head_year_ago"] == 65000
    assert s["pct_change"] == -2.2, "the YTD rate must not be a weekly rate"


def test_a_volume_that_is_not_head_is_refused():
    rejects = []
    assert cap.parse_slaughter([_slaughter_row(volume_unit="Pounds")], rejects) == []
    assert rejects and "Pounds" in rejects[0]


# ── gaps and staleness ──────────────────────────────────────────────────────

def test_the_year_end_closure_costs_two_iso_weeks_and_neither_is_reported():
    """THE BUG A CLEAN FIXTURE HID.

    The real ladder runs 2025-12-20 (ISO 2025-W51) straight to 2026-01-10
    (ISO 2026-W02): TWO ISO weeks lost, 52 and 1. An earlier draft excluded
    only week 1 and duly reported 2024-12-28 and 2025-12-27 as missing data --
    every year, for ever, on an annual closure. It passed its unit test and
    failed against the live feed.
    """
    rows = cap.parse_prices([
        _price_row(report_end_date="12/20/2025", published_date="12/30/2025 07:00:00"),
        _price_row(report_end_date="01/10/2026", published_date="01/20/2026 07:00:00"),
    ])
    assert cap.missing_weeks(rows) == []
    assert 52 in cap.HOLIDAY_ISO_WEEKS and 1 in cap.HOLIDAY_ISO_WEEKS


def test_a_genuinely_missing_week_is_reported():
    rows = cap.parse_prices([
        _price_row(report_end_date="08/15/2026", published_date="08/25/2026 07:00:00"),
        _price_row(report_end_date="08/29/2026", published_date="09/08/2026 07:00:00"),
    ])
    assert cap.missing_weeks(rows) == [(2026, 34)]


def test_a_correction_with_a_shifted_week_window_supersedes_the_original():
    """THE SECOND BUG A CLEAN FIXTURE HID, and it is live in the feed today.

    AMS republished the week of 2025-10-06 with a shifted window: the first
    publication (10/21) ended it Sunday 10/12, the correction (10/28) ended it
    Saturday 10/11. All 31 region/class/weight keys overlap exactly. Keyed on
    the raw week_ending both survive, latest_week picks the Sunday, and the
    page shows the figures AMS withdrew. Keyed on the ISO week they collapse
    and the later publication wins.
    """
    rows = cap.parse_prices([
        _price_row(report_end_date="10/12/2025", report_date="10/07/2025",
                   published_date="10/21/2025 07:00:00", current_price=380.00),
        _price_row(report_end_date="10/11/2025", report_date="10/06/2025",
                   published_date="10/28/2025 07:00:00", current_price=384.25),
    ])
    assert len(rows) == 1, "a correction must not survive as a second week"
    assert rows[0]["price"] == 384.25, "the later publication wins"
    assert rows[0]["week_ending"] == date(2025, 10, 11)


def test_a_sunday_week_ending_does_not_break_the_week_on_week_change():
    """A `-7 days` step is right 118 times in 119 and wrong across the one
    Sunday week_ending -- where it finds nothing and reports no change on a
    week that has one. ISO weeks do not have that failure mode."""
    rows = cap.parse_prices([
        _price_row(report_end_date="10/04/2025", published_date="10/14/2025 07:00:00",
                   current_price=370.00),
        _price_row(report_end_date="10/12/2025", published_date="10/21/2025 07:00:00",
                   current_price=380.00),
    ])
    latest, prior, change = cap.price_change(rows, "Alberta", "Steers", "601-700")
    assert (latest, prior, change) == (380.00, 370.00, 10.00)


def test_staleness_allows_the_measured_publication_lag():
    """Lag from week-ending to publication is 9-17 days, median 10. A rule
    written against the WEEKLY cadence marks this feed stale every single week
    on perfectly current data -- the defect that suppresses the board's
    leverage tension every Thursday."""
    rows = cap.parse_prices([_price_row()])
    week, behind, stale = cap.staleness(rows, date(2026, 10, 7))
    assert week == date(2026, 9, 26)
    assert behind == 11
    assert stale is False, "11 days behind is an ordinary week for this feed"
    assert cap.MAX_AGE_DAYS >= 17, "must clear the observed worst-case lag"


def test_a_genuinely_stopped_feed_is_marked():
    rows = cap.parse_prices([_price_row()])
    _, _, stale = cap.staleness(rows, date(2026, 11, 30))
    assert stale is True


def test_an_empty_series_is_stale_not_fresh():
    """An empty read must never look current. A page with no rows and no mark
    reads as a market with nothing to report."""
    week, behind, stale = cap.staleness([], date(2026, 10, 7))
    assert week is None and behind is None and stale is True


# ── the cache key ───────────────────────────────────────────────────────────

def test_schema_constant_exists_for_the_cache_key():
    """st.cache_data keys on the decorated function's own code and NEVER on the
    modules it calls. Without a SCHEMA in the key, a reshape of load() keeps
    serving a dict from before the new key existed and the tile renders "—"
    with nothing raising -- leverage.SCHEMA, am_cutout.SCHEMA, mx_prices.SCHEMA."""
    assert isinstance(cap.SCHEMA, int) and cap.SCHEMA >= 1


def test_the_absence_of_a_crossings_series_is_written_down():
    """There is no US-Canada livestock imports report in 1,051 MARS reports or
    151 LMR reports. That negative is the single most load-bearing fact about
    this module, and a future reader must not spend a day rediscovering it."""
    doc = cap.__doc__ or ""
    assert "NO US-CANADA CROSSINGS REPORT" in doc.upper()
    assert "3486" in doc and "3629" in doc
