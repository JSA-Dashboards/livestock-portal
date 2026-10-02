"""
A withheld price is not an undefined market, on the Daily Cash Trade tiles.

The companion to test_cash_suppression.py, which fixed the same defect in the
week-to-date VOLUME tiles. The PRICE tiles were deliberately left alone there
and went on rendering Kansas and TX/OK/NM as "Undefined -- no confirmed trade"
while USDA was withholding both under LMR confidentiality. "Undefined" is
USDA's own market test and is the right word on a quiet day; on these two it
says nobody has traded in Texas since June, which is false.

Verified against LMR /Detail over 2024-01-01..2026-10-02, all four regions,
both cuts, NEGOTIATED CASH Steer/Heifer "Total all grades" (22,540 rows):

  * On the 10/02/2026 file, TX/OK/NM and Kansas return every row with
    head_count AND wtd_avg_price None; Nebraska and Iowa/Minnesota price all
    of theirs. The rows exist and are blank -- the confidentiality signature,
    not a no-trade day.
  * USDA NEVER PUBLISHES A LITERAL 0: zero price==0 and zero head==0 rows in
    the whole window, matching the volume finding. So a blank cannot be read
    as a zero here either.
  * A BLANK VOLUME NEVER COINCIDES WITH A PUBLISHED PRICE -- 0 counterexamples
    in 2,833 region-trading-days. That is what licenses PREFERRING the volume
    `suppressed` flag over the price frame's own run: the flag can only fire
    on a day whose price is blank anyway, and one flag read by both panels is
    what keeps them agreeing by construction rather than by coincidence.
  * The converse is common and must NOT be called withheld: 316 days carry a
    week-to-date volume with no price that day, the region having traded
    earlier in the week and been quiet on it.
  * Blank-PRICE runs separate the same way the volume runs do -- ordinary
    stretches end at 6 (TX/OK/NM; 4 for the other three) against 33, 36 and 63
    where a region went dark -- so SUPPRESSION_RUN_DAYS sits in the gap on this
    series too.

Three states on each side, and the third is real: TX/OK/NM is absent from the
feed entirely on 3 days of the window (most recently 23-27 Jul 2026), which is
neither a blank nor a price.

A FOURTH STATE WAS ADDED 2026-10-02, because reusing the volume flag left a
hole that this file originally described as safe and was not. `suppressed`
defaulted to False, so a caller with no volume for a region asserted "not
withheld" and the tile fell back to "Undefined / no confirmed trade" -- the
original bug, verbatim. That is reachable without an exception: prices come
from each report's /Detail and head counts from its /Summary, and
_fetch_many's worker catches every exception per job and returns [], so a
Summary outage with Detail healthy leaves daily_err == "", passes the
`elif daily_df.empty` gate on a healthy price frame, and silently drops the
week-to-date panel. The page looked healthy while printing the false claim.

Reproduced 2026-10-02: TX/OK/NM ("--", "withheld by USDA") with both feeds up,
("Undefined", "no confirmed trade") with the volume frame emptied. The flag is
three-valued now -- True, False, None -- and None gets its own state and its
own caption, because no evidence either way is not evidence of no withholding.
The page warns as well, since nothing else can see this failure.

It does not cry wolf: over the 263 trading days to 2026-10-02, weekly_to_date()
returned {} on none of the days that carried a price, so the two sections move
together and an empty one is a real failure rather than a few hours of skew.

AND THEN THE PRICE FRAME LEARNED TO ANSWER FOR ITSELF. Saying "no volume data"
is honest but blind: a /Summary outage cost the page the withheld/quiet
distinction entirely, on a panel that already holds every row it needs to draw
it. _price_blank_run_days() counts the same kind of run on the price frame and
is consulted ONLY when the volume flag is absent, so the flag still decides
wherever it exists and the two panels still agree by construction.

The fallback is conservative in the same direction as the rest of this file: a
price run short of SUPPRESSION_RUN_DAYS is no more evidence of no withholding
than a missing flag was, so it yields "unknown" rather than "undefined" or a
claim. Nothing reaches "withheld" without a run long enough to have earned it
on one series or the other, and a published price beats both.
"""
import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from streamlit_source import load_from_app  # noqa: E402

APP = ROOT / "apps" / "cash_trade" / "app.py"


@pytest.fixture(scope="module")
def ns():
    return load_from_app(
        APP, "daily_price_state", "weekly_to_date", "_null_run_days",
        "_price_blank_run_days", "_trailing_blank_run",
        consts=("DAILY_REGIONS", "SUPPRESSION_RUN_DAYS"),
        globals_={"pd": pd},
    )


def _priced(rows):
    """daily_combined()-shaped rows: (basis, cut, price, head) tuples."""
    return pd.DataFrame(
        [{"region": "R", "basis": b, "cut": c, "price": p, "head": h}
         for b, c, p, h in rows],
        columns=["region", "basis", "cut", "price", "head"])


def _published(n=4):
    """fetch_daily_cash()-shaped rows, which KEEP the unpriced ones."""
    return pd.DataFrame([{"region": "R", "price": None}] * n)


NONE_PUBLISHED = pd.DataFrame(columns=["region", "price"])


# -- the bug ----------------------------------------------------------------

def test_a_withheld_region_is_not_an_undefined_market(ns):
    """The whole defect: USDA is holding the number back and the tile said
    nobody traded."""
    state, row = ns["daily_price_state"](_priced([]), _published(), suppressed=True)
    assert state == "withheld"
    assert row is None


def test_a_quiet_region_still_reads_undefined(ns):
    """
    USDA's own market-test language, and correct on a real no-trade day. The
    09/22/2026 dressed-only day is the case it was written for -- removing it
    would trade one wrong word for another.
    """
    state, row = ns["daily_price_state"](_priced([]), _published(), suppressed=False)
    assert state == "undefined"
    assert row is None


def test_a_region_absent_from_the_feed_is_a_third_state(ns):
    """
    Never published / published blank / published a number -- the same three
    the volume tiles use. TX/OK/NM really is absent on 3 days of the window,
    so this is not a hypothetical branch.
    """
    state, row = ns["daily_price_state"](_priced([]), NONE_PUBLISHED, suppressed=False)
    assert state == "unpublished"
    assert row is None


def test_suppressed_cannot_invent_a_withheld_day_out_of_nothing(ns):
    """An absent file is absent whatever the volume panel thinks."""
    assert ns["daily_price_state"](
        _priced([]), NONE_PUBLISHED, suppressed=True)[0] == "unpublished"


def test_no_volume_evidence_is_its_own_state(ns):
    """
    THIS TEST ASSERTED THE OPPOSITE AND THE OPPOSITE WAS WRONG.

    It read: a caller with no volume for the region must fall back to USDA's
    own word, not to a claim about USDA that nothing has established. Half of
    that holds -- defaulting to False does avoid a false WITHHELD. But
    "Undefined / no confirmed trade" is itself a claim, and a false one about
    a market that traded. Falling back to the bug is not a safe fallback.

    No volume evidence either way is not evidence of no withholding, so it
    gets a state of its own and the tile says it does not know.
    """
    assert ns["daily_price_state"](_priced([]), _published())[0] == "unknown"


def test_the_flag_is_three_valued(ns):
    """True, False and None are three different answers, not two and a null."""
    f, pr, pub = ns["daily_price_state"], _priced([]), _published()
    assert f(pr, pub, suppressed=True)[0] == "withheld"
    assert f(pr, pub, suppressed=False)[0] == "undefined"
    assert f(pr, pub, suppressed=None)[0] == "unknown"


def test_an_absent_file_outranks_a_missing_flag(ns):
    """
    "unpublished" is an observation about USDA; "unknown" is a statement about
    our own feed. The observation wins -- we know the file is not there
    whatever the volume panel did or did not say.
    """
    assert ns["daily_price_state"](
        _priced([]), NONE_PUBLISHED, suppressed=None)[0] == "unpublished"


def test_a_price_still_wins_when_the_flag_is_missing(ns):
    rows = _priced([("Live FOB", "morning", 221.25, 900.0)])
    state, row = ns["daily_price_state"](rows, _published(), suppressed=None)
    assert state == "priced"
    assert row["price"] == 221.25


def test_the_page_passes_none_rather_than_false_for_a_missing_entry(ns):
    """
    The whole fix lives in one expression. `bool(_entry and ...)` turns a
    missing volume row into False, which asserts "not withheld" -- the thing
    nothing established. A test pins the expression because the page code
    around it is not reachable from here.
    """
    src = APP.read_text(encoding="utf-8")
    assert 'suppressed=(_entry["suppressed"] if _entry else None)' in src
    assert 'suppressed=bool(_entry and _entry["suppressed"])' not in src


def test_the_page_warns_when_the_volume_feed_is_missing(ns):
    """
    daily_err structurally cannot see this: _fetch_many's worker catches every
    exception per job and returns [], so a Summary outage raises nothing and
    the `elif daily_df.empty` gate passes on a healthy PRICE frame. Without
    its own check the page renders "no volume data" tiles, drops the
    week-to-date panel, and reports itself healthy.
    """
    src = APP.read_text(encoding="utf-8")
    warn = src.index("if not wtd:")
    assert warn < src.index("_PRICE_BLANK = {"), "must warn above the tiles"
    block = src[warn:warn + 900]
    assert "st.warning(" in block
    assert "no volume data" in block, "must name what the tiles will say"


# -- the flag must never overwrite a real print -----------------------------

def test_a_price_always_wins_over_the_suppressed_flag(ns):
    """
    The licence for reusing the volume flag is that a blank volume never
    coincides with a published price -- 0 counterexamples in 2,833
    region-trading-days. If that ever stops holding, the price is still the
    answer: it is an observation, and the flag is an inference about one.
    """
    rows = _priced([("Live FOB", "morning", 235.50, 1200.0)])
    state, row = ns["daily_price_state"](rows, _published(), suppressed=True)
    assert state == "priced"
    assert row["price"] == 235.50


# -- the headline rules the old nested _headline() carried ------------------

def test_live_fob_is_preferred_to_dressed(ns):
    rows = _priced([("Live FOB", "morning", 235.50, 1200.0),
                    ("Dressed Delivered", "morning", 370.00, 800.0)])
    assert ns["daily_price_state"](rows, _published())[1]["basis"] == "Live FOB"


def test_it_must_fall_back_to_dressed(ns):
    """
    Tuesday 09/22/2026 traded dressed only -- Nebraska 2,349 steers and 550
    heifers at 350.00, no live FOB anywhere. Headlining Live FOB alone put
    "Undefined" on all four tiles on a day nearly 2,900 head traded.
    """
    rows = _priced([("Dressed Delivered", "morning", 350.00, 2899.0)])
    state, row = ns["daily_price_state"](rows, _published())
    assert state == "priced"
    assert row["basis"] == "Dressed Delivered"
    assert row["price"] == 350.00


def test_the_final_cut_beats_the_one_thirty_cut(ns):
    rows = _priced([("Live FOB", "afternoon", 234.00, 195.0),
                    ("Live FOB", "morning", 235.50, 584.0)])
    assert ns["daily_price_state"](rows, _published())[1]["cut"] == "morning"


def test_a_live_fob_afternoon_beats_a_dressed_morning(ns):
    """
    Basis is the outer loop and cut the inner one, so a live quote at 1:30
    still outranks a dressed final. That is the existing order, and the tile
    names the basis precisely because the four are not always the same quote.
    """
    rows = _priced([("Live FOB", "afternoon", 234.00, 195.0),
                    ("Dressed Delivered", "morning", 370.00, 800.0)])
    assert ns["daily_price_state"](rows, _published())[1]["basis"] == "Live FOB"


# -- the two panels have to agree -------------------------------------------

def _vol(series, days=25):
    dates = list(pd.bdate_range(end="2026-10-02", periods=days))
    rows = []
    for region, heads in series.items():
        heads = [None] * (len(dates) - len(heads)) + list(heads)
        for d, h in zip(dates, heads):
            rows.append({"region": region, "cut": "morning", "file_date": d,
                         "period": "wtd", "head": h, "head_week_ago": None,
                         "trade_date": d})
    return pd.DataFrame(rows), dates[-1]


def test_the_price_tile_takes_the_same_flag_the_volume_tile_shows(ns):
    """
    Both panels headline the same `last_trade`, so they line up by
    construction -- and the page computes weekly_to_date() once, above both,
    rather than twice. This pins the join: what weekly_to_date calls withheld
    is exactly what the price tile calls withheld.
    """
    vol, today = _vol({"Kansas": [None] * 25, "Nebraska": [3000.0] * 25})
    wtd = ns["weekly_to_date"](vol, today)

    assert wtd["Kansas"]["suppressed"] is True
    assert ns["daily_price_state"](
        _priced([]), _published(), suppressed=wtd["Kansas"]["suppressed"]
    )[0] == "withheld"

    # Nebraska is priced today, so it never reaches a blank state at all.
    assert wtd["Nebraska"]["suppressed"] is False
    assert ns["daily_price_state"](
        _priced([("Live FOB", "morning", 235.50, 1200.0)]), _published(),
        suppressed=wtd["Nebraska"]["suppressed"])[0] == "priced"


def test_a_quiet_day_inside_a_trading_week_stays_undefined(ns):
    """
    The common case, and the one a careless fix breaks: 316 days in the window
    carry a week-to-date volume with no price that day. The region traded
    earlier in the week and was quiet on this one -- "Undefined" is right and
    "withheld" would be a false accusation.
    """
    vol, today = _vol({"Nebraska": [3000.0] * 25})
    wtd = ns["weekly_to_date"](vol, today)
    assert wtd["Nebraska"]["suppressed"] is False
    assert ns["daily_price_state"](
        _priced([]), _published(), suppressed=wtd["Nebraska"]["suppressed"]
    )[0] == "undefined"


def test_a_short_blank_run_is_never_called_withheld(ns):
    """
    Four days is the longest ordinary blank run three regions have ever had,
    and six is TX/OK/NM's. Neither may be reported as confidentiality.
    """
    for run in (4, 6):
        vol, today = _vol({"Nebraska": [3000.0] * (25 - run) + [None] * run})
        wtd = ns["weekly_to_date"](vol, today)
        assert wtd["Nebraska"]["suppressed"] is False, run
        assert ns["daily_price_state"](
            _priced([]), _published(), suppressed=wtd["Nebraska"]["suppressed"]
        )[0] == "undefined", run


def test_the_threshold_clears_the_longest_ordinary_price_run(ns):
    """
    The volume threshold is reused on the price series, so it has to clear the
    PRICE runs too: ordinary stretches end at 6, suppression runs reach 33.
    """
    assert 6 < ns["SUPPRESSION_RUN_DAYS"] <= 33


# -- the page still renders every state -------------------------------------

def test_the_page_has_a_rendering_for_every_state(ns):
    """
    daily_price_state returns five states and the page maps four of them to a
    blank tile by name. A state added without a caption would be a KeyError on
    the live page, which is worse than a wrong word.

    Derived from the function rather than listed by hand, so a sixth state
    cannot be added without a caption and still pass.
    """
    src = APP.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "daily_price_state")
    returned = {c.value for n in ast.walk(fn) if isinstance(n, ast.Return)
                for c in ast.walk(n)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    blank_states = returned - {"priced"}
    assert blank_states == {"withheld", "undefined", "unpublished", "unknown"}

    start = src.index("_PRICE_BLANK = {")
    block = src[start:src.index("cols = st.columns(len(DAILY_REGIONS))", start)]
    for state in blank_states:
        assert f'"{state}":' in block, state
    assert "withheld by USDA" in block
    assert "no confirmed trade" in block
    assert "no volume data" in block


def test_weekly_to_date_is_computed_once_above_both_panels(ns):
    """
    Script order decides what is available, not tab order. The price tiles need
    the flag, so the call has to sit above them -- and calling it twice would
    let the two panels disagree about which regions are withheld, the class of
    bug where both numbers are defensible and nothing raises.
    """
    src = APP.read_text(encoding="utf-8")
    assert src.count("weekly_to_date(daily_vol, last_trade)") == 1
    assert (src.index("wtd = weekly_to_date(daily_vol, last_trade)")
            < src.index("_PRICE_BLANK = {"))


# -- the prose has to track the code -----------------------------------------

def test_the_footnote_does_not_hardcode_the_threshold(ns):
    """
    The footnote explains the rule to a reader, so a changed
    SUPPRESSION_RUN_DAYS has to change the sentence too. Prose that drifts from
    the code is this repo's recurring defect -- it reads as documentation and
    is wrong, which is worse than silence.
    """
    src = APP.read_text(encoding="utf-8")
    assert "f'{SUPPRESSION_RUN_DAYS} trading days is a region that has gone dark" in src
    assert "a run reaching ten" not in src


def test_the_quiet_day_banner_handles_every_region_withheld(ns):
    """
    `_quiet` means nothing priced anywhere, which is exactly what four withheld
    regions look like -- so the branch is reachable, not hypothetical. Built by
    subtraction it would render "no confirmed negotiated trade in ." with an
    empty region list.
    """
    src = APP.read_text(encoding="utf-8")
    block = src[src.index("if _quiet:"):src.index("_PRICE_BLANK = {")]
    assert "elif not _open_q:" in block
    assert "withholding every region for confidentiality" in block
    # and the partial case still names only the regions it can speak for
    assert "no confirmed negotiated trade in '" in block
    assert "and_list(_open_q)" in block


# -- the table under the tiles says the same thing ---------------------------

def test_the_table_carries_the_same_distinction_as_the_tiles(ns):
    """
    Every cell in a withheld row is a dash, and a dash says nothing. The table
    gets a status column rather than text in the price cells, which would
    repeat the same sentence four times across one row.
    """
    src = APP.read_text(encoding="utf-8")
    start = src.index("# ── Both cuts, side by side")
    block = src[start:src.index("st.dataframe(pd.DataFrame(grid)", start)]
    assert 'entry["USDA status"]' in block
    # the wording comes from the same table the tiles read, not a second copy
    assert "_PRICE_BLANK[_state][1]" in block
    assert "withheld by USDA" not in block, "the table must not re-spell the captions"


def test_a_priced_region_gets_an_empty_status_cell(ns):
    """
    The row speaks for itself. Filling it with "published" would bury the two
    rows that are actually saying something.
    """
    src = APP.read_text(encoding="utf-8")
    start = src.index("# ── Both cuts, side by side")
    block = src[start:src.index("st.dataframe(pd.DataFrame(grid)", start)]
    assert '"" if _state == "priced"' in block


def test_the_tiles_and_the_table_resolve_the_state_once(ns):
    """
    Two callers deciding separately are two callers free to disagree -- a table
    reading "no confirmed trade" beside a tile reading "withheld by USDA" would
    be this very defect, one row lower. Same reasoning as the single
    weekly_to_date() call.
    """
    src = APP.read_text(encoding="utf-8")

    # ast, not a substring count: "daily_price_state()" also appears in a
    # comment two lines above the call, and a test that matches prose instead
    # of code is the mistake streamlit_source.py's own docstring warns about.
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "daily_price_state"]
    assert len(calls) == 1, [n.lineno for n in calls]

    body = src[src.index("with tab_daily:"):]
    assert "state, row = _states[region]" in body       # the tiles
    assert "_state = _states[region][0]" in body        # the table
    assert (body.index("_states[region] = daily_price_state(")
            < body.index("state, row = _states[region]")
            < body.index("_state = _states[region][0]"))


# -- the price frame answering for itself ------------------------------------

def _prices(series, days=25):
    """
    fetch_daily_cash()-shaped rows, newest LAST: (head, price) or None for a
    day USDA published blank. A day omitted is a day USDA did not publish.
    """
    dates = list(pd.bdate_range(end="2026-10-02", periods=days))
    vals = [None] * (len(dates) - len(series)) + list(series)
    return pd.DataFrame([
        {"region": "R", "cut": "morning", "basis": "Live FOB",
         "trade_date": d, "head": (v or (None, None))[0],
         "price": (v or (None, None))[1]}
        for d, v in zip(dates, vals)
    ]), dates[-1]


def test_the_price_run_rescues_a_withheld_region_when_the_flag_is_gone(ns):
    """
    The point of the fallback: a /Summary outage no longer blinds the panel.
    TX/OK/NM has published nothing but blanks since 2026-06-26, and the price
    frame alone is enough to say so.
    """
    f = ns["daily_price_state"]
    long_run = ns["SUPPRESSION_RUN_DAYS"]
    assert f(_priced([]), _published(), suppressed=None,
             blank_run=long_run)[0] == "withheld"


def test_a_short_price_run_still_yields_unknown(ns):
    """
    Conservative in the same direction as everything else here. Six sessions
    is TX/OK/NM reporting normally in a thin week, not a withholding, and with
    no flag to corroborate it the honest answer is still "I cannot tell".
    """
    f = ns["daily_price_state"]
    assert f(_priced([]), _published(), suppressed=None, blank_run=6)[0] == "unknown"
    assert f(_priced([]), _published(), suppressed=None, blank_run=0)[0] == "unknown"


def test_the_flag_wins_wherever_it_exists(ns):
    """
    A fallback, not a second opinion. Two detectors free to disagree are two
    panels free to disagree -- the defect this file exists for, one row lower.
    A long price run must not override a flag that says otherwise.
    """
    f = ns["daily_price_state"]
    long_run = ns["SUPPRESSION_RUN_DAYS"] + 20
    assert f(_priced([]), _published(), suppressed=False,
             blank_run=long_run)[0] == "undefined"
    assert f(_priced([]), _published(), suppressed=True, blank_run=0)[0] == "withheld"


def test_a_price_beats_a_long_blank_run(ns):
    """An observation outranks an inference about one, the same as the flag."""
    rows = _priced([("Live FOB", "morning", 219.75, 800.0)])
    state, row = ns["daily_price_state"](rows, _published(), suppressed=None,
                                         blank_run=99)
    assert state == "priced"
    assert row["price"] == 219.75


def test_an_absent_file_beats_a_long_blank_run(ns):
    assert ns["daily_price_state"](_priced([]), NONE_PUBLISHED, suppressed=None,
                                   blank_run=99)[0] == "unpublished"


def test_the_price_run_counts_only_unusable_days(ns):
    """
    "Usable" is head AND price, which is what daily_combined keeps -- a row
    with one of the two is still a blank day to the tile, so the run has to
    agree with what the tile rendered.
    """
    f = ns["_price_blank_run_days"]
    df, today = _prices([None] * 25)
    assert f(df, "R", today) == 25
    df, today = _prices([None] * 24 + [(500.0, None)])
    assert f(df, "R", today) == 25
    df, today = _prices([None] * 24 + [(None, 220.0)])
    assert f(df, "R", today) == 25
    df, today = _prices([None] * 24 + [(500.0, 220.0)])
    assert f(df, "R", today) == 0


def test_the_price_run_resets_on_a_print(ns):
    df, today = _prices([None] * 20 + [(500.0, 220.0)] + [None] * 4)
    assert ns["_price_blank_run_days"](df, "R", today) == 4


def test_the_price_run_is_zero_for_a_region_not_in_the_frame(ns):
    df, today = _prices([(500.0, 220.0)] * 25)
    assert ns["_price_blank_run_days"](df, "Elsewhere", today) == 0


def test_the_price_run_ignores_days_after_the_one_asked_about(ns):
    """The tiles headline last_trade; the run must describe that day."""
    df, _ = _prices([(500.0, 220.0)] * 20 + [None] * 5)
    earlier = list(pd.bdate_range(end="2026-10-02", periods=25))[19]
    assert ns["_price_blank_run_days"](df, "R", earlier) == 0


def test_trailing_blank_run_skips_days_usda_never_published(ns):
    """
    An unpublished day is not in the map: it neither counts toward the run nor
    breaks it, because the run is about what USDA said when it spoke.
    """
    days = list(pd.bdate_range(end="2026-10-02", periods=5))
    flags = {days[0]: True, days[1]: True, days[3]: True, days[4]: True}
    assert ns["_trailing_blank_run"](flags, days[4]) == 4
    flags[days[1]] = False
    assert ns["_trailing_blank_run"](flags, days[4]) == 2


def test_both_series_share_one_definition_of_a_run(ns):
    """
    Two near-identical loops is how a module ends up existing five times in
    this repo. Both detectors must delegate rather than re-implement.
    """
    src = APP.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for name in ("_null_run_days", "_price_blank_run_days"):
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        calls = {c.func.id for c in ast.walk(fn)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "_trailing_blank_run" in calls, name


def test_the_page_feeds_the_run_into_the_single_call(ns):
    """
    Invariant 1 says daily_price_state resolves once. The fallback therefore
    takes the run as an argument rather than adding a second call site, and
    the run is computed from the PRICE frame the panel already holds.
    """
    src = APP.read_text(encoding="utf-8")
    assert "blank_run=_price_blank_run_days(daily_df, region, last_trade)" in src
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "daily_price_state"]
    assert len(calls) == 1, [n.lineno for n in calls]
