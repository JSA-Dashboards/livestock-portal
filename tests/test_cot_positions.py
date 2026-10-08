"""
The CFTC Commitments of Traders reader -- apps/cot_report/cot_positions.py.

Every assertion here is about a failure that RENDERS PERFECTLY. A net on the
wrong report basis, a sign carried by punctuation the audience reads backwards,
a staleness rule off by one release, a percentile measured against a window the
label does not name: none of them raise, none of them look wrong on a tile, and
every one produces a number a trader would act on.

THE FIXTURE IS REAL AND THAT IS DELIBERATE. CFTC's figures are public, so
unlike tests/test_sterling.py there is nothing to protect by synthesising them,
and a fixture carrying the real numbers is the only kind that can check an
identity against arithmetic a human can do in their head: 81,722 - 28,529 is
53,193, and 1,452 - -2,651 is 4,103.

THE PIN THAT MATTERS MOST is `test_the_page_and_the_friday_letter_cannot_drift`.
`letter/render.cftc_block()` already prints these two figures every Friday from
a completely different source -- the live CFTC Socrata API, via
`letter/sources.fetch_cftc()` -- and CLAUDE.md records three mornings lost to
two JSA surfaces quoting one figure and disagreeing. The two agree today to the
contract. This file is what notices if that stops being true.
"""
import ast
import importlib.util
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "_test_cot_positions", REPO / "apps" / "cot_report" / "cot_positions.py")
cot = importlib.util.module_from_spec(spec)
sys.modules["_test_cot_positions"] = cot
spec.loader.exec_module(cot)


# -- the real report, 2026-09-22 and 2026-09-29, futures only ----------------

ROWS = [
    dict(series="LIVE_CATTLE", report_date="2026-09-22", open_interest=284889,
         open_interest_chg=2771, mm_long=80270, mm_short=31180, mm_spread=42165,
         mm_net=49090, mm_long_chg=-416, mm_short_chg=-1810, mm_long_traders=73,
         mm_short_traders=31, traders_total=374, prod_merc_long=42214,
         prod_merc_short=129757, prod_merc_net=-87543, swap_long=68038,
         swap_short=3722, swap_spread=1568, swap_net=64316, other_long=12902,
         other_short=33680, other_spread=12685, other_net=-20778,
         nonrept_long=25047, nonrept_short=30132, nonrept_net=-5085),
    dict(series="LIVE_CATTLE", report_date="2026-09-29", open_interest=293639,
         open_interest_chg=8750, mm_long=81722, mm_short=28529, mm_spread=45318,
         mm_net=53193, mm_long_chg=1452, mm_short_chg=-2651, mm_long_traders=72,
         mm_short_traders=35, traders_total=386, prod_merc_long=42153,
         prod_merc_short=137427, prod_merc_net=-95274, swap_long=69039,
         swap_short=3758, swap_spread=1397, swap_net=65281, other_long=14347,
         other_short=32372, other_spread=14015, other_net=-18025,
         nonrept_long=25648, nonrept_short=30823, nonrept_net=-5175),
    dict(series="FEEDER_CATTLE", report_date="2026-09-22", open_interest=61983,
         open_interest_chg=2350, mm_long=16242, mm_short=8237, mm_spread=11528,
         mm_net=8005, mm_long_chg=467, mm_short_chg=-327, mm_long_traders=40,
         mm_short_traders=26, traders_total=224, prod_merc_long=7820,
         prod_merc_short=9647, prod_merc_net=-1827, swap_long=6674,
         swap_short=621, swap_spread=1971, swap_net=6053, other_long=1683,
         other_short=14147, other_spread=5505, other_net=-12464,
         nonrept_long=10560, nonrept_short=10327, nonrept_net=233),
    dict(series="FEEDER_CATTLE", report_date="2026-09-29", open_interest=62168,
         open_interest_chg=185, mm_long=17364, mm_short=9198, mm_spread=10252,
         mm_net=8166, mm_long_chg=1122, mm_short_chg=961, mm_long_traders=40,
         mm_short_traders=22, traders_total=214, prod_merc_long=7111,
         prod_merc_short=10020, prod_merc_net=-2909, swap_long=7204,
         swap_short=244, swap_spread=1719, swap_net=6960, other_long=2408,
         other_short=12655, other_spread=6514, other_net=-10247,
         nonrept_long=9596, nonrept_short=11566, nonrept_net=-1970),
]

# CFTC's older Legacy report for the same two weeks. Non-commercial is managed
# money PLUS other reportables, which is why feeder cattle is net SHORT here
# while managed money is net LONG.
LEGACY_ROWS = [
    dict(series="LIVE_CATTLE", report_date="2026-09-29", noncomm_net=35168),
    dict(series="FEEDER_CATTLE", report_date="2026-09-29", noncomm_net=-2081),
]


def frame(rows=None):
    df = pd.DataFrame(rows if rows is not None else ROWS)
    df["report_date"] = pd.to_datetime(df["report_date"])
    return df


def one(series, rows=None):
    return cot.market(frame(rows), series)


# -- the identities ----------------------------------------------------------

def test_net_is_long_less_short_on_every_fixture_row():
    for r in ROWS:
        assert r["mm_net"] == r["mm_long"] - r["mm_short"], r["series"]


def test_the_five_category_nets_sum_to_zero_exactly():
    """
    Every long contract is somebody's short. On the futures-only basis this is
    exact -- zero residual on all 2,120 cattle rows since 2006 -- which is why
    OI_TOLERANCE is 0 and not a comfortable few contracts.
    """
    for r in ROWS:
        total = sum(r[f"{k}_net"] for k, _ in cot.CATEGORIES)
        assert total == 0, (r["series"], r["report_date"], total)


def test_audit_refuses_a_row_whose_net_does_not_match_its_legs():
    bad = [dict(r) for r in ROWS]
    bad[-1]["mm_net"] += 7          # renders perfectly; wrong by seven contracts
    out = cot.reconciles(frame(bad))
    assert out["net_ok"] is False and out["net_bad"] == 1


def test_audit_refuses_a_published_change_that_does_not_match_the_levels():
    """
    CFTC's MM_LONG_CHG must equal the diff of MM_LONG on adjacent weeks. It does
    on all 1,037 futures-only pairs, so a mismatch means a revision landed
    without its change column, or the weeks have been mis-joined.
    """
    bad = [dict(r) for r in ROWS]
    bad[1]["mm_long_chg"] += 1
    out = cot.reconciles(frame(bad))
    assert out["chg_ok"] is False and out["chg_bad"] >= 1


def test_the_clean_fixture_passes_every_audit():
    out = cot.reconciles(frame())
    assert out["net_ok"] and out["chg_ok"] and out["oi_ok"]
    assert out["oi_worst"] == 0


def test_oi_tolerance_stays_zero():
    """
    A tolerance on an identity that is exact is a hole, not a safeguard: it lets
    a shifted column of that many contracts through silently. The ±3 residual
    that justifies slack belongs to the COMBINED basis, which this page does not
    audit and does not lead with.
    """
    assert cot.OI_TOLERANCE == 0


# -- the headline figures ----------------------------------------------------

def test_the_page_and_the_friday_letter_cannot_drift():
    """
    `letter/sources.fetch_cftc()` computes net as long-less-short and the weekly
    change as MM_LONG_CHG - MM_SHORT_CHG off CFTC's live API. `latest()` must
    produce the identical arithmetic off Snowflake, or the Friday letter and
    this dashboard will quote the same figure and disagree -- the failure
    CLAUDE.md records three times.

    Verified against both live paths on 2026-10-07: 120 rows, 60 weeks x 2
    markets, zero mismatches on net, long, short and week-over-week.
    """
    live = cot.latest(one("LIVE_CATTLE"))
    assert live["net"] == 53193
    assert live["wow"] == 4103          # 1,452 - -2,651
    feeder = cot.latest(one("FEEDER_CATTLE"))
    assert feeder["net"] == 8166
    assert feeder["wow"] == 161         # 1,122 - 961


def test_the_weekly_change_is_cftcs_own_column_not_our_diff():
    """
    They agree on every futures-only week, so this is not about the number --
    it is about which one we take. CFTC's published change survives a revision
    to an older week correctly, and taking the published figure is what stops
    this page and the letter reaching the same number by two different routes.
    """
    g = one("LIVE_CATTLE")
    head = cot.latest(g)
    assert head["wow"] == g.iloc[-1]["mm_long_chg"] - g.iloc[-1]["mm_short_chg"]


def test_a_single_row_history_yields_no_weekly_change_rather_than_zero():
    g = one("LIVE_CATTLE", [ROWS[1]])
    head = cot.latest(g)
    assert head["net"] == 53193
    assert head["prev_net"] is None


# -- the sign, which must never be punctuation -------------------------------

@pytest.mark.parametrize("net,expected", [
    (53193, "long"), (-2081, "short"), (0, "flat"), (None, ""),
])
def test_side_names_the_direction_in_a_word(net, expected):
    assert cot.side(net) == expected


def test_no_helper_ever_wraps_a_number_in_parentheses():
    """
    In CFTC's and USDA's own reports parentheses mean NEGATIVE -- the trap
    `letter/sterling.py` and `apps/beef_cutout/am_cutout.py` both document. A
    net short feeder position rendered "(9,589)" reads to this audience as a
    LONG of 9,589. `side()` is the whole mechanism for keeping the sign out of
    punctuation, so it must never return one.
    """
    for net in (53193, -2081, 0, -1, 1):
        assert "(" not in cot.side(net) and ")" not in cot.side(net)


# -- what drove the week -----------------------------------------------------

def test_short_covering_is_distinguished_from_new_buying():
    """
    Live Cattle's +4,103 was longs adding 1,452 and shorts covering 2,651 -- the
    shorts carried it. A page showing only the net cannot tell a market being
    chased from one squeezing people out.
    """
    w = cot.why(cot.latest(one("LIVE_CATTLE")))
    assert w["driver"] == "short"
    assert w["phrase"] == "short covering"
    assert w["agree"] is True


def test_both_legs_moving_together_is_not_reported_as_one_leg():
    """
    Feeder Cattle added 1,122 longs AND 961 shorts, so the net moved 161 while
    more than two thousand contracts of gross exposure went on. Calling that
    "new buying" because the long leg was marginally larger is true and
    misleading in one phrase.
    """
    w = cot.why(cot.latest(one("FEEDER_CATTLE")))
    assert w["agree"] is False
    assert w["phrase"] == "longs and shorts both added"


def test_both_legs_cut_reads_as_liquidation():
    rows = [dict(r) for r in ROWS]
    rows[3]["mm_long_chg"], rows[3]["mm_short_chg"] = -800, -300
    w = cot.why(cot.latest(one("FEEDER_CATTLE", rows)))
    assert w["agree"] is False
    assert w["phrase"] == "longs and shorts both liquidated"


def test_a_week_with_no_movement_says_so_rather_than_naming_a_driver():
    rows = [dict(r) for r in ROWS]
    rows[3]["mm_long_chg"] = rows[3]["mm_short_chg"] = 0
    w = cot.why(cot.latest(one("FEEDER_CATTLE", rows)))
    assert w["driver"] is None
    assert w["phrase"] == "neither leg moved"


# -- the reconciliation that stops the phone call ----------------------------

def test_legacy_non_commercial_is_managed_money_plus_other_reportables():
    """
    An identity, not an approximation: it holds with zero error on all 1,060
    weeks of both cattle markets. It is the whole explanation of why this page
    and a broker's screen can disagree, so it is asserted rather than described.
    """
    for lr in LEGACY_ROWS:
        row = next(r for r in ROWS
                   if r["series"] == lr["series"] and r["report_date"] == "2026-09-29")
        assert lr["noncomm_net"] == row["mm_net"] + row["other_net"], lr["series"]


def test_the_feeder_sign_split_is_detected():
    """
    Live on 2026-09-29 and in 133 of 1,060 feeder weeks: managed money net LONG
    8,166 while the legacy report's non-commercial is net SHORT 2,081. If this
    goes undetected the page states one and the client reads the other.
    """
    leg = frame(LEGACY_ROWS)
    g = one("FEEDER_CATTLE")
    rec = cot.reconciliation(cot.latest(g), {"net": 7638}, leg, "FEEDER_CATTLE",
                             other_net=-10247)
    assert rec["legacy_net"] == -2081
    assert rec["sign_split"] is True
    assert rec["identity_ok"] is True


def test_live_cattle_agrees_in_sign_and_is_not_flagged():
    leg = frame(LEGACY_ROWS)
    g = one("LIVE_CATTLE")
    rec = cot.reconciliation(cot.latest(g), {"net": 51304}, leg, "LIVE_CATTLE",
                             other_net=-18025)
    assert rec["legacy_net"] == 35168
    assert rec["sign_split"] is False


def test_the_cross_view_audit_catches_a_mis_joined_series():
    leg = frame([dict(LEGACY_ROWS[0]), dict(LEGACY_ROWS[1])])
    assert cot.reconciles_across_views(frame(), leg)["ok"] is True
    broken = frame([dict(LEGACY_ROWS[0], noncomm_net=35168),
                    dict(LEGACY_ROWS[1], noncomm_net=2081)])   # sign flipped
    out = cot.reconciles_across_views(frame(), broken)
    assert out["ok"] is False and out["bad"] == 1


# -- the release calendar ----------------------------------------------------

@pytest.mark.parametrize("now,expected", [
    # Positions are as of Tuesday and published the following Friday. The hour
    # is this page's own: Snowflake is filled by the 3pm CT ETL, not by CFTC's
    # 2:30pm release, so a 4pm cutoff leaves the job an hour to finish.
    (datetime(2026, 10, 7, 14, 0), date(2026, 9, 29)),   # Wed  -> last Friday's
    (datetime(2026, 10, 9, 13, 0), date(2026, 9, 29)),   # Fri before the hour
    (datetime(2026, 10, 9, 16, 30), date(2026, 10, 6)),  # Fri after the hour
    (datetime(2026, 10, 10, 9, 0), date(2026, 10, 6)),   # Sat
    (datetime(2026, 10, 12, 9, 0), date(2026, 10, 6)),   # Mon
])
def test_expected_report_date_follows_the_release_not_the_calendar(now, expected):
    assert cot.expected_as_of(now) == expected


def test_a_current_report_is_not_called_stale():
    out = cot.is_current(date(2026, 9, 29), datetime(2026, 10, 7, 14, 0))
    assert out["current"] is True and out["weeks_behind"] == 0


def test_a_holiday_monday_report_date_is_still_current():
    """
    When Tuesday is a federal holiday the report date slips BACK to the Monday
    -- 13 times in 1,060 weeks. A rule demanding the exact Tuesday would cry
    stale on a perfectly fresh report, every one of those weeks.
    """
    out = cot.is_current(date(2026, 10, 5), datetime(2026, 10, 9, 16, 30))
    assert out["current"] is True


def test_a_week_behind_is_reported_as_a_week_behind():
    out = cot.is_current(date(2026, 9, 22), datetime(2026, 10, 7, 14, 0))
    assert out["current"] is False
    assert out["weeks_behind"] == 1


def test_three_weeks_behind_counts_the_weeks():
    out = cot.is_current(date(2026, 9, 8), datetime(2026, 10, 7, 14, 0))
    assert out["current"] is False and out["weeks_behind"] == 3


def test_a_missing_as_of_is_not_current():
    assert cot.is_current(None, datetime(2026, 10, 7, 14, 0))["current"] is False


def test_positions_are_aged_from_the_tuesday_they_were_struck():
    """
    A current report still describes a Tuesday that is a week gone by the
    Wednesday after. That is a different question from `is_current()` and the
    one a reader needs before acting on the number.
    """
    assert cot.position_age_days(date(2026, 9, 29), datetime(2026, 10, 7, 9, 0)) == 8


# -- context -----------------------------------------------------------------

def test_percentile_refuses_a_sample_too_short_to_mean_anything():
    """
    None rather than 50.0: "the sample is too short to say" and "it is bang in
    the middle" are different answers and a page that merges them is lying
    quietly.
    """
    assert cot.percentile(pd.Series(range(10)), 5) is None
    assert cot.percentile(pd.Series(range(200)), 100) == pytest.approx(50.0, abs=1)


def test_a_year_ago_is_taken_by_date_and_not_by_counting_rows():
    """
    Fifty-two weeks is 364 days, and the drift compounds: over twenty years it
    walks the comparison a fortnight out of season. The fixture's two rows are
    seven days apart, so there is no reading a year back and the module must
    say so rather than reaching for the oldest row it has.
    """
    c = cot.context(one("LIVE_CATTLE"))
    assert c["net_year_ago"] is None and c["chg_year"] is None


def test_the_run_on_this_side_of_the_market_resets_when_the_net_flips():
    rows = [dict(ROWS[2], mm_net=-500, mm_long=7737, mm_short=8237),
            dict(ROWS[3])]
    c = cot.context(one("FEEDER_CATTLE", rows))
    assert c["weeks_on_this_side"] == 1          # net long for one week only
    assert c["weeks_net_short"] == 1


def test_records_are_reported_with_the_week_they_were_set():
    c = cot.context(one("LIVE_CATTLE"))
    assert c["record_high"] == 53193
    assert c["record_high_on"] == date(2026, 9, 29)
    assert c["record_low"] == 49090


def test_net_as_a_share_of_open_interest_is_carried():
    """
    Feeder cattle open interest has roughly doubled since 2006-2010, so a
    contract count is not comparable across the full history and the share is.
    """
    c = cot.context(one("FEEDER_CATTLE"))
    assert c["net_pct_oi"] == pytest.approx(100 * 8166 / 62168, abs=1e-9)


def test_series_frame_trims_by_date_and_carries_the_share():
    fr = cot.series_frame(one("LIVE_CATTLE"))
    assert list(fr.columns)[:3] == ["report_date", "mm_net", "mm_long"]
    assert "net_pct_oi" in fr.columns


# -- decomposition -----------------------------------------------------------

def test_decompose_returns_every_category_and_they_balance():
    rows = cot.decompose(one("LIVE_CATTLE"))
    assert [r["key"] for r in rows] == [k for k, _ in cot.CATEGORIES]
    assert cot.categories_balance(rows) == 0


def test_the_producer_side_is_short_against_a_long_fund():
    """
    Managed money net long 53,193 is half a sentence; producers, merchants and
    processors net short 95,274 is the other half.
    """
    rows = {r["key"]: r for r in cot.decompose(one("LIVE_CATTLE"))}
    assert rows["mm"]["net"] == 53193 and rows["mm"]["side"] == "long"
    assert rows["prod_merc"]["net"] == -95274 and rows["prod_merc"]["side"] == "short"


# -- module hygiene ----------------------------------------------------------

def _module_source():
    return (REPO / "apps" / "cot_report" / "cot_positions.py").read_text(encoding="utf-8")


def test_the_module_never_reads_snowflake_schema():
    """
    NINE bundled modules each default SNOWFLAKE_SCHEMA to the schema they own,
    so setting it to any one value silently breaks the others. This module reads
    a tenth schema and must take no part in that: every statement names
    JSA.CFTC_COT in full.

    ASSERTED BY AST AND NOT BY GREP, because the module's own docstring explains
    the rule and names the variable -- the exact failure
    tests/test_am_cutout.py records, where a grep-based version of this test
    failed on the comment describing what it was checking.
    """
    tree = ast.parse(_module_source())
    names = {n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    # Strip docstrings, which legitimately discuss the rule.
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    assert not {s for s in (names - docs) if "SNOWFLAKE_SCHEMA" in s}


def test_snowflake_db_is_loaded_under_a_private_name():
    """
    snowflake_db.py exists five times in this repo and Python caches modules by
    NAME, so a plain `import snowflake_db` binds whichever page loaded first.
    """
    tree = ast.parse(_module_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name != "snowflake_db" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "snowflake_db"
    assert "_cot_db" in _module_source()


def test_the_module_has_no_http_path():
    """
    It is a Snowflake reader. The letter reaches CFTC's API directly and that is
    the one place that should; a second live fetcher would be a second answer to
    the same question. Asserted by AST so the docstring may discuss it.
    """
    tree = ast.parse(_module_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] != "requests" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "requests"


def test_there_is_exactly_one_copy_of_this_module():
    """
    The `snowflake_db`-times-five lesson applied before the fact. A second
    cot_positions.py under another app directory would mean whichever page
    loaded first decided which copy every other page got.
    """
    assert len(list(REPO.rglob("cot_positions.py"))) == 1


def test_the_views_are_named_in_full():
    assert cot.VIEW == "JSA.CFTC_COT.COT_DISAGG"
    assert cot.LEGACY_VIEW == "JSA.CFTC_COT.COT_LEGACY"


def test_the_headline_basis_is_futures_only():
    """
    COMBINED gives Live Cattle 51,304 against 53,193 -- plausible, different,
    and silent if chosen by mistake. The letter uses futures only; so does this.
    """
    assert cot.FUT == "FUT"
    src = _module_source()
    assert "report_type: str = FUT" in src


# -- the page ----------------------------------------------------------------

def _page_source():
    return (REPO / "apps" / "cot_report" / "app.py").read_text(encoding="utf-8")


def test_the_reconciliation_renders_above_the_tabs():
    """
    It exists to stop a client ringing about a number that disagrees with his
    broker's screen, and a section below four charts cannot do that. Pinned by
    source position, the same way the WASDE panel is pinned above Cash Cattle
    Trade's outage guard.
    """
    src = _page_source()
    recon = src.index("The same week, quoted three ways")
    tabs = src.index("tab_live, tab_feeder, tab_compare = st.tabs")
    assert recon < tabs


def test_the_as_of_line_renders_before_the_headline_figures():
    """
    The commonest way this report is misread is as a current position. The
    dateline has to be met first.
    """
    src = _page_source()
    assert src.index('class="asof"') < src.index("hero_cols = st.columns(2)")


def test_the_cache_key_argument_is_not_underscore_prefixed():
    """
    STREAMLIT IGNORES ANY PARAMETER WHOSE NAME BEGINS WITH AN UNDERSCORE when it
    computes a cache key -- that is the documented mechanism for passing
    unhashable things like a connection into a cached function. So the
    `_schema=mod.SCHEMA` form used elsewhere in this repo keys nothing at all
    and bumping the constant changes nothing.

    Measured, not assumed: with `_schema`, calling f(), f(2), f(1) ran the body
    once; with `schema`, calling g(), g(2), g(1) ran it three times. The trap it
    guards fired on this very page during development, survived two server
    restarts via persist="disk", and printed the wrong sentence without raising.
    """
    src = _page_source()
    assert "def load_cot(schema: int = cot.SCHEMA, epoch=None)" in src
    assert "_schema" not in src.split("def load_cot")[1][:400]


# -- picking up Friday's report on Friday ------------------------------------

@pytest.mark.parametrize("now,epoch,alarm", [
    # CFTC publishes 2:30pm CT; the ETL loads Snowflake at 3pm. The FETCH
    # threshold rolls at 3, the ALARM threshold at 4, and between them the page
    # is looking for the new week without yet complaining that it is missing.
    (datetime(2026, 10, 9, 14, 0),  date(2026, 9, 29), date(2026, 9, 29)),
    (datetime(2026, 10, 9, 14, 45), date(2026, 9, 29), date(2026, 9, 29)),  # CFTC out, ETL not run
    (datetime(2026, 10, 9, 15, 5),  date(2026, 10, 6), date(2026, 9, 29)),  # look, do not shout
    (datetime(2026, 10, 9, 16, 5),  date(2026, 10, 6), date(2026, 10, 6)),  # both rolled
    (datetime(2026, 10, 12, 9, 0),  date(2026, 10, 6), date(2026, 10, 6)),  # Monday
])
def test_the_fetch_threshold_leads_the_alarm_threshold_by_an_hour(now, epoch, alarm):
    assert cot.data_epoch(now) == epoch
    assert cot.expected_as_of(now) == alarm


def test_the_cache_epoch_rolls_over_exactly_once_a_week():
    """
    It is a cache key, so what matters is that it is STABLE between releases and
    CHANGES at one. A value that moved more often would refetch for nothing; one
    that moved less would serve a week-old position on the day it mattered.
    """
    seen = []
    for day in range(14):
        for hour in (0, 9, 14, 15, 16, 23):
            seen.append(cot.data_epoch(datetime(2026, 10, 1 + day, hour, 0)))
    distinct = sorted(set(seen))
    # Oct 1-14 spans the Friday releases of Oct 2 and Oct 9 only, so three
    # epochs: the one standing on Oct 1, and one for each release.
    assert distinct == [date(2026, 9, 22), date(2026, 9, 29), date(2026, 10, 6)]
    # and it only ever moves forward as the clock does
    assert seen == sorted(seen)


def test_the_page_passes_the_epoch_into_the_cached_loader():
    """
    The constant is useless unless it reaches the cache key. `st.cache_data`
    hashes the ARGUMENTS, so a `data_epoch()` that nothing passes in is a
    function with no callers wearing a comment.
    """
    src = (REPO / "apps" / "cot_report" / "app.py").read_text(encoding="utf-8")
    assert "load_cot(epoch=cot.data_epoch())" in src
    assert "def load_cot(schema: int = cot.SCHEMA, epoch=None)" in src


def test_the_etl_hour_precedes_the_alarm_hour():
    """
    If these ever cross, the page starts complaining that data is missing before
    it has looked for it.
    """
    assert cot.ETL_HOUR_CT < cot.RELEASE_HOUR_CT
