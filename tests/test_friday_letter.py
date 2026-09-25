"""
Guards for the Friday letter's three additions: CFTC, regional cash, Cattle on Feed.

These are pure-logic and constant checks -- nothing here hits the network, so
the suite stays runnable with no key and no connection. What they protect is the
set of choices that fail SILENTLY if they drift: the wrong CFTC dataset, the
wrong report variant, a class filter that widens a price range, and a COF block
that includes itself on the wrong week.

    python -m pytest tests/test_friday_letter.py -q
"""
from __future__ import annotations

from datetime import date

import pytest

from pathlib import Path as _Path

from letter import cof, commentary, config, render, sources

REPO_ROOT = _Path(__file__).resolve().parent.parent


# -- CFTC ---------------------------------------------------------------------

def test_cftc_uses_the_live_disaggregated_dataset():
    """
    publicreporting.cftc.gov carries a FROZEN duplicate of this report
    (ubmb-6exi) last updated in 2022. It answers happily with four-year-old
    positions and no error, so the id is pinned.
    """
    assert "72hh-3qpy" in sources.CFTC_DATASET
    assert "ubmb-6exi" not in sources.CFTC_DATASET


def test_cftc_contract_codes():
    """
    Filtering is on contract_market_code, never commodity_code -- the latter
    comes back in two whitespace variants ('057' and '057 ') so an equality
    filter silently drops rows.
    """
    assert sources.CFTC_MARKETS == {"057642": "Live Cattle", "061641": "Feeder Cattle"}
    src = (sources.REPO / "letter" / "sources.py").read_text(encoding="utf-8")
    assert "cftc_contract_market_code in(" in src
    assert "cftc_commodity_code in(" not in src


@pytest.mark.parametrize("as_of, issue, expected", [
    # Friday 9/18 letter with the 9/15 report -- that week's Tuesday. Current.
    ("2026-09-15", date(2026, 9, 18), True),
    # The trap: built Friday morning, before the 3:30pm ET release.
    ("2026-09-08", date(2026, 9, 18), False),
    ("2026-09-22", date(2026, 9, 22), True),   # a Tuesday issue
    (None, date(2026, 9, 18), False),
])
def test_cftc_currency_check(as_of, issue, expected):
    assert sources.cftc_is_current({"as_of": as_of} if as_of else {}, issue) is expected


def test_cftc_block_prints_the_date_from_the_data():
    """
    The 9/18/26 letter was headed "as of 9/8/26" while carrying the 9/15
    report's numbers. The date must come from the same rows as the figures.
    """
    html = render.cftc_block({
        "as_of": "2026-09-15",
        "markets": {"Live Cattle": {"net_long": 47696, "wow": -1209},
                    "Feeder Cattle": {"net_long": 7211, "wow": -237}},
    })
    assert "as of 9/15/26" in html
    assert "47,696" in html and "-1,209" in html
    assert "7,211" in html and "-237" in html


# -- Regional cash ------------------------------------------------------------

def test_am_uses_the_summary_reports_not_the_afternoon_ones():
    """
    Nebraska on Monday 2026-09-21: the Afternoon report carried zero priced
    rows, the Summary carried nine. A week-to-date built on Afternoon silently
    dropped a state that had traded.

    The evening letter keeps the Afternoon slugs on purpose -- 9/18 Afternoon
    gives the letter's own 220-222.50, where the Summary runs to 224.00.
    """
    am = {slug for slug, _ in sources.CASH_STATES}
    pm = {slug for group in sources.CASH_REGIONS.values() for slug in group}
    assert am == {2668, 2672, 2664, 2666}
    assert pm == {2667, 2671, 2663, 2665}
    assert not (am & pm)


def test_cash_regions_and_class_filter():
    """
    North is Nebraska plus the Western Cornbelt; South is TX/OK/NM plus Kansas.
    The class filter is load-bearing: adding MIXED STEER/HEIFER or the
    ALL BEEF TYPE rollup widens the verified 220.00-222.50 to 218.00-222.50,
    and DAIRYBRED drags the dressed range down to 320.00.
    """
    assert set(sources.CASH_REGIONS) == {"North", "South"}
    assert set(sources.CASH_REGIONS["North"]) == {2667, 2671}
    assert set(sources.CASH_REGIONS["South"]) == {2663, 2665}
    assert sources.CASH_CLASSES == ("STEER", "HEIFER")


def test_undefined_region_is_printed_not_marked_missing():
    """
    "South: Undefined" is USDA's own state for too little confirmed trade. It is
    a real answer and must never render as a [[?]] gap.
    """
    html = render.cash_cattle_block({"regions": {
        "North": {"live_low": 220.0, "live_high": 222.5,
                  "dressed_low": 346.0, "dressed_high": 350.0, "undefined": False},
        "South": {"live_low": None, "live_high": None,
                  "dressed_low": None, "dressed_high": None, "undefined": True},
    }})
    assert "220.00-222.50 FOB live" in html
    assert "South: Undefined" in html
    assert render.MISSING not in html


# -- Cattle on Feed -----------------------------------------------------------

@pytest.mark.parametrize("release, issue, expected", [
    (date(2026, 9, 18), date(2026, 9, 18), True),    # released that Friday
    (date(2026, 9, 18), date(2026, 9, 25), False),   # the next Friday: omit
    (date(2026, 8, 21), date(2026, 9, 18), False),   # last month's: omit
    (date(2026, 9, 22), date(2026, 9, 25), True),    # same Mon-Sun week
])
def test_cof_week_detection(release, issue, expected):
    """
    latest_report() walks back thirteen months and so almost always returns
    SOMETHING. Keying off existence would print a stale table on the three
    Fridays a month with no release.
    """
    assert cof.released_this_week(release, issue) is expected


def test_cof_block_omitted_when_not_included():
    assert render.cof_block({"include": False, "reason": "x"}) == ""
    assert render.cof_block({}) == ""
    assert render.cof_block(None) == ""


def test_cof_block_renders_computed_figures_and_dashes_missing_guesses():
    """
    Guesses are typed in -- USDA does not publish them and nothing derives them.
    A missing one is an em dash, not a [[?]]: there is no source to have failed.
    """
    html = render.cof_block({
        "include": True, "title": "Sep COF Report",
        "actual": {"on_feed": 100.7, "placed": 90.8, "marketed": 96.7},
        "year_ago": {"on_feed": 98.9, "placed": 90.1, "marketed": 86.4},
        "guesses": {},
    })
    assert "100.7" in html and "98.9" in html
    assert "&mdash;" in html
    assert render.MISSING not in html


# -- Section wiring -----------------------------------------------------------

def _pm_ctx(commentary_sections: dict, kind: str = "tuesday") -> dict:
    """
    The thinnest evening-letter context build_html will render.

    Deliberately empty of figures: these tests are about which sections appear
    and in what order, and a fixture full of prices would make them fail for
    reasons that have nothing to do with that.
    """
    return {
        "kind": kind, "session": "pm", "issue_date": date(2026, 9, 23),
        "change_basis": "week", "live_cattle": [], "feeder_cattle": [],
        "cash": {}, "cutout": {}, "slaughter": {},
        "commentary": commentary_sections,
    }


def test_the_two_letters_have_different_sections():
    tue = dict(commentary.sections_for("tuesday"))
    fri = dict(commentary.sections_for("friday"))
    assert "market_action" in tue and "market_action" not in fri
    assert "fundamental" in tue and "fundamental" not in fri
    assert "key_headlines" in fri and "cash_recap" in fri and "cof_note" in fri
    # Shared on purpose: a technical read means the same thing in both.
    assert "technicals_lc" in tue and "technicals_lc" in fri


def test_the_evening_letter_leads_with_headlines():
    """
    Added 2026-09-23. The standard PM letter gained a Headlines section, placed
    ahead of Market Action the way Friday leads with Key Headlines and the
    morning brief leads with Headlines.
    """
    tue = dict(commentary.sections_for("tuesday"))
    assert "headlines" in tue

    # Order in SECTIONS_BY_KIND is the order they appear in the letter.
    keys = [k for k, _ in commentary.sections_for("tuesday")]
    assert keys.index("headlines") < keys.index("market_action")

    html = render.build_html(_pm_ctx({
        "headlines": ["Kansas ICE sweep has packers delaying shifts"],
        "market_action": ["Board closed higher across the front."],
    }))
    assert html.index("<h2>Headlines</h2>") < html.index("<h2>Market Action</h2>")


def test_friday_still_replaces_market_action_rather_than_adding_to_it():
    """
    Friday's Key Headlines took Market Action's place; it did not join it. The
    PM change must not turn Friday into both.
    """
    html = render.build_html(_pm_ctx(
        {"key_headlines": ["Week in review"], "market_action": ["must not appear"]},
        kind="friday"))
    assert "<h2>Key Headlines</h2>" in html
    assert "Market Action" not in html
    assert "must not appear" not in html


def test_a_pm_letter_with_nothing_typed_prints_no_headline_heading():
    """Same rule as every other section: blank means absent, not empty."""
    html = render.build_html(_pm_ctx({}))
    assert "Headlines" not in html


def test_draft_filenames_are_per_letter(tmp_path):
    """
    A Tuesday draft read as Friday would silently drop Key Headlines and the
    Cash Trade Recap, so the kind is in the filename.
    """
    t = commentary.path_for(tmp_path, date(2026, 9, 22), "tuesday")
    f = commentary.path_for(tmp_path, date(2026, 9, 22), "friday")
    assert t != f


def test_friday_rundown_words_the_yoy_rates():
    html = render.friday_rundown_block(
        {}, {"weekly": {"value": 529000, "last_week": 505000, "year_ago": 559000,
                        "ytd_chg_pct": -7.5},
             "beef_production": {"ytd_chg_pct": -5.1}}, {}, {}, {})
    assert "529,000 compared to 505,000 head LW and 559,000 LY" in html
    assert "7.5% lower YoY" in html
    assert "5.1% lower YoY" in html


def test_moving_averages_survive_the_json_round_trip():
    """
    THE GUARD MOVED, THE HAZARD DID NOT. technicals.build returns int keys and
    the context is cached to JSON between the fetch and the --no-fetch
    re-render, so ma[9] comes back as ma["9"]. render.technicals_block carried
    this until the averages stopped printing on 2026-09-25; removing it there
    left hints quoting "9-day MA None" as the figure to write against.
    """
    import json
    from letter import build as letter_build
    tech = {"month": "Oct", "ma": {9: 220.11, 20: 219.42}, "complete": True}
    ctx = {"live_cattle": [], "feeder_cattle": [], "tech_lc": json.loads(json.dumps(tech)),
           "tech_fc": None, "change_basis": "day", "cash": {}, "cutout": {}, "slaughter": {},
           "outside": [], "calendar": [], "daily_slaughter": {}, "carcass_weights": {},
           "fci": {}, "douglas": {}, "cftc": {}, "regional_cash": {}, "cof": {}}
    ma_lines = [l for l in letter_build.hints(ctx, "tuesday")["technicals_lc"] if "MA" in l]
    assert any("220.11" in l for l in ma_lines)
    assert any("219.42" in l for l in ma_lines)
    assert not any("None" in l for l in ma_lines)

    # and nothing anywhere in the draft quotes a bare None at Ross
    all_lines = " ".join(letter_build.hints(ctx, "tuesday")["technicals_lc"])
    assert "None" not in all_lines


def test_gapped_technicals_are_flagged_in_the_draft():
    """
    A 9-day mean over a series missing a week read 216.392 where the letter's
    own figure was 218.90. Wrong, not approximate.

    The letter used to mark that [[?]] when it printed the averages. It no
    longer prints them -- Ross writes the Technicals himself as of 2026-09-25 --
    so the warning has to reach the DRAFT instead. A wrong number restated in
    his own prose carries no [[?]] at all, which makes this more important than
    when the renderer owned it, not less.
    """
    from letter import build as letter_build
    tech = {"month": "Oct", "ma": {9: 216.392, 20: 215.216},
            "complete": False, "gaps": ["2026-09-14"]}
    ctx = {"live_cattle": [], "feeder_cattle": [], "tech_lc": tech, "tech_fc": None,
           "change_basis": "day", "cash": {}, "cutout": {}, "slaughter": {},
           "outside": [], "calendar": [], "daily_slaughter": {}, "carcass_weights": {},
           "fci": {}, "douglas": {}, "cftc": {}, "regional_cash": {}, "cof": {}}
    lines = " ".join(letter_build.hints(ctx, "tuesday")["technicals_lc"])
    assert "DO NOT QUOTE" in lines
    assert "2026-09-14" in lines

    # ...and nothing computed reaches the letter either way
    assert render.technicals_block(tech, [], "Live Cattle") == ""


def test_cutout_pm_label_comes_from_the_report_date():
    """
    LM_XB403 PM publishes ~3pm Central. A letter written earlier carries the
    previous session's cutout, and calling that "Tues PM" on a Tuesday is a
    false claim about which print it is.
    """
    tues = render.rundown_block({}, {}, {"report_date": "2026-09-22",
                                         "choice": {"value": 378.89, "change": 2.54}})
    mon = render.rundown_block({}, {}, {"report_date": "2026-09-21",
                                        "choice": {"value": 376.35, "change": 4.41}})
    assert "Tues PM." in tues
    assert "Mon PM." in mon and "Tues PM." not in mon


def test_ams_string_payload_means_no_rows_not_a_crash():
    """
    AMS answers 200 with a bare JSON STRING when a date has no report -- not an
    error status, not an empty list. Iterating that as sections walks its
    characters and dies on str.get, which took the whole Cash Cattle Trade
    section down on a date with no published trade.
    """
    import letter.sources as S

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return "No results found."

    class _Sess:
        def get(self, *a, **k): return _Resp()

    real, S._session = S._session, lambda *a, **k: _Sess()
    try:
        assert S._cash_rows(2667, date(2026, 9, 25)) == []
    finally:
        S._session = real


# -- Weekday selection --------------------------------------------------------

def test_the_three_pm_formats():
    """
    Five weekdays, three evening formats. The full letter opens the week on
    MONDAY, the recap carries Tuesday through Thursday, and Friday is the
    week-in-review.

    THE ID "tuesday" NOW RUNS ONLY ON MONDAY. The ids are layout names with a
    historical spelling, not days -- see config.FORMAT_FOR_DAY. This test is
    where that is most likely to look like a typo, so: it is not one.

    An unknown day falls to the full letter, not the recap -- if the day cannot
    be determined, send more rather than less.
    """
    from letter import config
    assert config.format_for("monday") == "tuesday"      # the FULL letter
    assert config.format_for("friday") == "friday"
    for d in ("tuesday", "wednesday", "thursday"):
        assert config.format_for(d) == "recap", d
    assert config.format_for("nonsense") == "tuesday"


def test_the_three_middle_days_are_alike():
    """Ross's reason for the swap: Tue/Wed/Thu should be one letter, not two."""
    from letter import config
    kinds = {config.format_for(d) for d in ("tuesday", "wednesday", "thursday")}
    assert len(kinds) == 1


def test_the_recap_is_the_light_letter():
    """
    Added 2026-09-24 for Mon/Wed/Thu. One written technicals block instead of
    two, and no Fundamental Rundown -- those are what make Tuesday heavy.
    """
    keys = [k for k, _ in commentary.sections_for("recap")]
    assert keys == ["headlines", "market_action", "technicals", "comments"]
    assert "fundamental" not in keys
    assert "technicals_lc" not in keys and "technicals_fc" not in keys


def test_the_recap_did_not_disturb_the_other_two():
    """
    Ross asked for the full letter and the week-in-review to keep their own
    sections when the recap was added. Comments arrived later and deliberately
    went on ALL THREE, so it is expected here -- everything before it is what
    those two letters have always had.
    """
    tue = [k for k, _ in commentary.sections_for("tuesday")]
    fri = [k for k, _ in commentary.sections_for("friday")]
    assert tue == ["headlines", "market_action", "technicals_lc",
                   "technicals_fc", "fundamental", "comments"]
    assert fri == ["key_headlines", "technicals_lc", "technicals_fc",
                   "cash_recap", "cof_note", "comments"]


def test_the_recap_prints_one_technicals_read_not_two():
    """
    While the averages printed, the single combined read landed after an "Oct
    Feeders" heading and read as though it were about feeders alone. With
    nothing computed left to head, the section is just the read -- once.
    """
    ctx = _pm_ctx({"technicals": ["Holding the 20-day."]}, kind="recap")
    ctx["tech_lc"] = {"month": "Oct", "ma": {9: 220.0, 20: 219.0}, "complete": True}
    ctx["tech_fc"] = {"month": "Oct", "ma": {9: 336.0, 20: 334.0}, "complete": True}
    html = render.build_html(ctx)
    assert html.count("Holding the 20-day.") == 1
    assert "<h2>Technicals</h2>" in html
    # nothing computed, and no per-product sub-heading for the read to sit under
    assert "220.00" not in html and "336.00" not in html
    assert "moving average" not in html


def test_the_recap_keeps_its_signature_inline():
    """
    That one page break was the difference between two sheets and three, which
    is most of what "lighter" was supposed to buy. Tuesday and Friday keep the
    signature page.
    """
    recap = render.build_html(_pm_ctx({"market_action": ["x"]}, kind="recap"))
    tuesday = render.build_html(_pm_ctx({"market_action": ["x"]}, kind="tuesday"))
    assert "sig own-page" not in recap
    assert "sig own-page" in tuesday


def test_the_am_report_ignores_the_weekday_entirely():
    """One morning format, all five days -- the recap must not leak into it."""
    from letter import config
    for d in config.DAYS:
        assert config.format_for(d.lower(), "am") == "am", d


def test_day_defaults_from_the_issue_date():
    from letter import config
    assert config.day_for_date(date(2026, 9, 21)) == "monday"
    assert config.day_for_date(date(2026, 9, 23)) == "wednesday"
    assert config.day_for_date(date(2026, 9, 25)) == "friday"
    # A weekend date has no letter of its own; clamp rather than crash.
    assert config.day_for_date(date(2026, 9, 26)) == "friday"
    assert config.day_for_date(date(2026, 9, 27)) == "monday"


def test_week_base_is_shared_by_every_letter_in_the_week(tmp_path):
    """
    The prior Friday's settle is a property of the WEEK. Keying it per letter
    meant retyping the same six numbers on Monday, Tuesday, Wednesday...
    """
    from letter import build as B
    paths = {B.week_base_path(tmp_path, date(2026, 9, d), day)
             for d, day in ((21, "monday"), (22, "tuesday"),
                            (23, "wednesday"), (24, "thursday"))}
    assert len(paths) == 1
    assert "2026-09-18" in paths.pop().name

    # A letter on the Friday itself measures from the PREVIOUS Friday.
    assert B.prior_friday_of(date(2026, 9, 25)) == date(2026, 9, 18)


def test_settle_log_files_prices_under_their_own_settle_date(tmp_path):
    """
    Recorded against the contract's settle_date, not the issue date. When the
    newest bar lags -- a holiday, a late print -- those differ, and filing a
    price under the wrong day is the error this exists to prevent.
    """
    from letter import settle_log
    p = tmp_path / "log.json"
    ctx = {"live_cattle": [{"ticker": "LEV6", "settle": 220.775,
                            "settle_date": "2026-09-23"}],
           "feeder_cattle": [{"ticker": "GFU6", "settle": 337.175,
                              "settle_date": "2026-09-22"}]}
    assert settle_log.record(ctx, p) == 2
    assert settle_log.settles_on(date(2026, 9, 23), p) == {"LEV6": 220.775}
    assert settle_log.settles_on(date(2026, 9, 22), p) == {"GFU6": 337.175}

    # Last write wins: a rebuild after the close corrects an intraday value.
    ctx["live_cattle"][0]["settle"] = 220.5
    settle_log.record(ctx, p)
    assert settle_log.settles_on(date(2026, 9, 23), p) == {"LEV6": 220.5}


def test_cof_block_punctuation_matches_the_sent_letter():
    """
    The 9/18/26 letter reads "September COF Report", with a trailing hyphen on
    each row label and colons on the first two column heads but not Year-Ago.
    cof_recap's own title abbreviates the month for the dashboard's narrower
    page, so the letter rebuilds it.
    """
    html = render.cof_block({
        "include": True, "title": "September COF Report",
        "actual": {"on_feed": 100.7, "placed": 90.8, "marketed": 96.7},
        "year_ago": {"on_feed": 98.9, "placed": 90.1, "marketed": 86.4},
        "guesses": {"on_feed": 101.8, "placed": 96.8, "marketed": 96.1},
    })
    assert "September COF Report" in html and "Sep COF Report" not in html
    for label in ("On-Feed-", "Placed-", "Marketed-"):
        assert f"<td>{label}</td>" in html
    assert "<th>Actual:</th>" in html and "<th>Guesses:</th>" in html
    assert "<th>Year-Ago</th>" in html
    # Placed and Marketed reproduce the letter exactly; only On-Feed and the
    # Year-Ago basis differ, and that difference is the documented rounding one.
    for v in ("90.8", "96.8", "90.1", "96.7", "96.1", "86.4", "101.8"):
        assert v in html


def test_bare_build_resolves_the_issue_date_before_deriving_the_day():
    """
    With no --date and no --day the weekday is derived from the issue date, so
    the date has to be resolved first. It was not: `python -m letter.build` with
    no arguments -- the most ordinary invocation there is -- died with
    UnboundLocalError on `issue`.
    """
    import inspect
    from letter import build as B
    src = inspect.getsource(B.main)
    assert src.index("issue = date.fromisoformat") < src.index("config.day_for_date(issue)")
    assert src.count("issue = date.fromisoformat") == 1


# -- The AM morning brief -----------------------------------------------------

def test_am_is_one_format_every_weekday():
    """
    The morning brief does not switch to the week-in-review on a Friday the way
    the evening letter does -- there is no week to review at 07:30.
    """
    from letter import config
    for d in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        assert config.format_for(d, "am") == "am", d
    assert config.format_for("friday", "pm") == "friday"


@pytest.mark.parametrize("value, expected", [
    (531.25, "531'2"),      # how Ross writes it: "-8'6 at 528", "at 531'2"
    (5.5, "5'4"),
    (-8.75, "-8'6"),
    # A whole cent drops the eighths: "528", not "528'0".
    (528.0, "528"),
    (-9.0, "-9"),
    # Rounds UP into the whole cent rather than producing 530'8, which is not a
    # price anyone would recognise.
    (530.9999, "531"),
])
def test_grain_quotes_in_eighths(value, expected):
    assert render.eighths(value) == expected


def test_overnight_quote_shape():
    """
    "Dec Corn: -8'6 at 528" -- month before the commodity, change before the
    price, joined by "at". Every line in the brief is "Label: value".
    """
    html = render.am_blocks(
        {"outside": [{"label": "Corn", "month": "Dec", "style": "eighths",
                      "price": 528.0, "change": -8.75}]}, {})
    assert "Dec Corn: -8'6 at 528" in "".join(html).replace("&nbsp;", " ")


def test_fci_heading_and_no_second_date():
    """The heading says Estimate and the brief is dated at the top; a date on
    the value line is one more thing to read past."""
    html = "".join(render.am_blocks(
        {"fci": {"value": 336.98, "date": "2026-09-22", "change": -1.76}}, {}))
    assert "JSA FCI Estimate" in html
    assert "2026-09-22" not in html
    # Same "change at price" shape as the overnight quotes.
    assert "Estimate: -1.76 at 336.98" in html.replace("&nbsp;", " ")


def test_am_collapses_two_undefined_cash_regions_into_one_line():
    """Two lines saying "Undefined" is two lines saying nothing."""
    ctx = {"regional_cash": {"regions": {
        "North": {"undefined": True}, "South": {"undefined": True}}}}
    joined = "".join(render.am_blocks(ctx, {}))
    assert "No established test" in joined
    assert "North:" not in joined


def test_am_never_carries_the_evening_rundown():
    """
    The brief is the product. A section added to the PM letter must not be able
    to appear here -- build_html returns early for AM rather than opting out
    block by block.
    """
    ctx = {"kind": "am", "session": "am", "issue_date": date(2026, 9, 23),
           "change_basis": "week", "live_cattle": [], "feeder_cattle": [],
           "cash": {}, "cutout": {}, "slaughter": {}, "commentary": {}}
    html = render.build_html(ctx)
    for absent in ("Technicals", "Cattle market rundown", "Fundamental Rundown",
                   "Last week", "CFTC"):
        assert absent not in html, absent
    assert "Upcoming USDA Reports" in html


# -- Headline candidates ------------------------------------------------------

def _am_ctx(contracts: list, issue: date) -> dict:
    """
    An AM context that actually reaches the futures band.

    The band is nested inside the FCI guard -- no index value, no Cattle
    Futures block at all -- so `fci` is not optional scaffolding here.
    """
    return {"kind": "am", "session": "am", "issue_date": issue,
            "change_basis": "day", "live_cattle": contracts, "feeder_cattle": [],
            "fci": {"value": 337.0, "change": 0.5},
            "cash": {}, "cutout": {}, "slaughter": {}, "commentary": {}}


def test_the_am_futures_heading_names_the_settlement_date():
    """
    Added 2026-09-24. The AM block quotes yesterday's settle on a page dated
    today, so the heading says which session that was.
    """
    ctx = _am_ctx([{"month": "Oct", "settle": 220.5, "change_day": 1.0,
                    "settle_date": "2026-09-23"}], date(2026, 9, 24))
    html = render.build_html(ctx)
    assert "Settlement on 9/23/26" in html
    assert '<h2>Cattle Futures <span class="asof">' in html


def test_the_settlement_date_comes_from_the_contract_not_the_calendar():
    """
    THE POINT OF READING settle_date. On a Monday the prior session is Friday,
    and issue-minus-one would print Sunday -- a date on which nothing settled.
    """
    monday = date(2026, 9, 21)
    ctx = _am_ctx([{"month": "Oct", "settle": 220.5, "change_day": 1.0,
                    "settle_date": "2026-09-18"}], monday)
    assert render._settle_stamp(ctx) == "9/18/26"
    assert "Settlement on 9/18/26" in render.build_html(ctx)


def test_an_undated_contract_drops_the_label_rather_than_guessing():
    ctx = _am_ctx([{"month": "Oct", "settle": 220.5, "change_day": 1.0}],
                  date(2026, 9, 24))
    assert render._settle_stamp(ctx) == ""
    html = render.build_html(ctx)
    assert "<h2>Cattle Futures</h2>" in html
    assert "Settlement on" not in html


def test_the_morning_brief_has_no_intro_line():
    """
    Removed 2026-09-24. "Morning report for 9/24/26:" sat directly under a
    masthead reading "JSA AM Daily Cattle Report 9/24/26" -- the same two facts
    twice, at the top of a brief whose budget is three minutes.
    """
    html = render.build_html(_am_ctx(
        [{"month": "Oct", "settle": 220.5, "change_day": 1.0,
          "settle_date": "2026-09-23"}], date(2026, 9, 24)))
    assert "JSA AM Daily Cattle Report 9/24/26" in html
    assert "Morning report for" not in html
    # Not an empty paragraph either -- the element is absent.
    assert 'class="intro"' not in html


@pytest.mark.parametrize("kind,expected", [
    # _pm_ctx issues on 9/23; the point is the wording, not the date.
    ("tuesday", "For the week through the close on 9/23/26:"),
    ("friday", "For the week of 9/23/26:"),
])
def test_the_evening_intros_stay(kind, expected):
    """
    They are not redundant: they name the PERIOD the letter covers, which the
    masthead does not. Only the morning one restated its own heading.
    """
    html = render.build_html(_pm_ctx({"market_action": ["x"], "key_headlines": ["x"]},
                                     kind=kind))
    assert expected in html


def test_an_intro_renders_again_if_one_is_put_back(monkeypatch):
    """The line is gone by configuration, not by deletion."""
    monkeypatch.setattr(config, "INTRO_AM", "Morning report for {stamp}:")
    html = render.build_html(_am_ctx(
        [{"month": "Oct", "settle": 220.5, "change_day": 1.0,
          "settle_date": "2026-09-23"}], date(2026, 9, 24)))
    assert "Morning report for 9/24/26:" in html


def test_headlines_never_reach_the_letter():
    """
    The candidate panel is a pick list on the authoring page. Nothing it fetches
    can render into the brief on its own -- the only headline text in the letter
    comes from the commentary the user typed.
    """
    from letter import headlines
    ctx = {"kind": "am", "session": "am", "issue_date": date(2026, 9, 23),
           "change_basis": "week", "live_cattle": [], "feeder_cattle": [],
           "cash": {}, "cutout": {}, "slaughter": {},
           "commentary": {}}          # nothing typed
    html = render.build_html(ctx)
    assert "Headlines" not in html

    # The renderer must have no way to reach the fetcher: it renders what was
    # typed, and cannot go and get something to print on its own.
    src = (sources.REPO / "letter" / "render.py").read_text(encoding="utf-8")
    assert "import headlines" not in src
    assert "headlines." not in src


def test_headline_relevance_filter():
    """
    The feeds are general agriculture. Without a cattle filter the panel fills
    with corn agronomy and stops being worth opening.
    """
    from letter import headlines
    assert headlines._RELEVANT.search("Cattle futures drop on export rumors")
    assert headlines._RELEVANT.search("Tracking path of New World screwworm")
    assert not headlines._RELEVANT.search("Wind and wet conditions delay Ohio soybean harvest")


def test_digest_parser_keeps_headlines_and_drops_chrome():
    """
    A digest is a list of linked headlines wrapped in marketing furniture. The
    furniture is the same in every one of them; the headlines are not.
    """
    from letter import mailbox
    html = """
      <a href="#">View this in your browser</a>
      <a href="#">Cattle futures drop on export rumors as packers stay sidelined</a>
      <a href="#">Cargill Fort Morgan ramps second shift, sources say</a>
      <a href="#">Read more</a><a href="#">Unsubscribe</a>
      <a href="#">Manage your preferences</a>
      <a href="#">ok</a>
    """
    got = mailbox.parse_headlines(html, "html")
    assert "Cattle futures drop on export rumors as packers stay sidelined" in got
    assert "Cargill Fort Morgan ramps second shift, sources say" in got
    assert len(got) == 2          # every piece of chrome dropped


def test_mailbox_never_blocks_the_build():
    """
    An unconfigured or signed-out mailbox is one line in the panel, not a failed
    morning -- and never an interactive prompt during a scheduled run.
    """
    from letter import mailbox
    import os
    saved = {k: os.environ.pop(k, None) for k in ("GRAPH_CLIENT_ID", "GRAPH_TENANT_ID")}
    try:
        assert mailbox.configured() is False
        access, problem = mailbox.token(interactive=False)
        assert access is None and "error" in problem
        got = mailbox.fetch_digests()
        assert got["items"] == [] and got["errors"] and got["needs_sign_in"] is True
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_digests_are_configured_as_data_not_code():
    """Adding a publication should be one line, and each needs a way to find it."""
    from letter import mailbox
    labels = {d["label"] for d in mailbox.DIGESTS}
    assert labels == {"Meatingplace", "eMeat", "Global AgriTrends", "Sterling"}
    assert all(d.get("sender") or d.get("sender_name") or d.get("subject")
               or d.get("match") for d in mailbox.DIGESTS)


def test_a_sender_address_is_an_exact_filter_not_a_body_search():
    """
    $search reads the BODY as well as the sender, so "sterling" would also match
    a client email about sterling silver and surface its text in the panel. A
    known From address must produce an exact $filter instead.
    """
    from letter import mailbox
    src = (sources.REPO / "letter" / "mailbox.py").read_text(encoding="utf-8")
    assert "from/emailAddress/address eq" in src

    assert "startswith(from/emailAddress/name," in src  # prefix, also body-free

    by_label = {d["label"]: d for d in mailbox.DIGESTS}
    # Meatingplace's address is not visible in the client; the display name is.
    assert by_label["Meatingplace"]["sender_name"] == "Meatingplace Editorial"
    assert "match" not in by_label["Meatingplace"]
    # The Bulletin, not "The EMEAT Team" -- that one is the publisher's
    # marketing, and a prefix match keeps it out.
    assert by_label["eMeat"]["sender_name"] == "The EMEAT Daily Bulletin"
    assert "match" not in by_label["eMeat"]
    # CORRECTED 2026-09-25. This asserted globalagritrends.com, which is what
    # the config said and not what the publisher sends from -- so the test
    # passed every day while the source matched nothing at all. A test that
    # checks a constant against itself cannot notice the constant is wrong;
    # tests/test_mailbox.py now also asserts the shape that caught it.
    assert by_label["Global AgriTrends"]["sender"] == "no-reply@agritrends.com"
    assert "match" not in by_label["Global AgriTrends"]
    # "sterling" alone is far too common a word to search bodies for.
    assert by_label["Sterling"]["sender"] == "jnalivka@fmtc.com"
    assert "match" not in by_label["Sterling"]

    # Not every digest is a daily. Sterling's newest on 2026-09-23 was Monday
    # afternoon, ~45h old; a 30-hour window dropped it silently.
    import inspect
    assert "max_age_h: int = 72" in inspect.getsource(mailbox.fetch_digests)


def test_the_page_never_states_the_mapping_from_memory():
    """
    The bug this prevents: the Letter radio's help text was a hardcoded
    sentence, so when Monday and Tuesday swapped formats it went on describing
    the old arrangement -- while the caption beside it, which reads `kind`, had
    already updated. The page contradicted itself, and only a human reading both
    would notice.

    Anything that states the mapping in words must be generated from it.
    """
    from letter import config
    src = (REPO_ROOT / "apps" / "weekly_reports" / "app.py").read_text(encoding="utf-8")
    assert "config.pm_format_summary()" in src
    for stale in ("Tuesday is the full", "Mon/Wed/Thu the shorter",
                  "the rest share the standard"):
        assert stale not in src, f"mapping written out by hand: {stale!r}"


def test_the_summary_follows_the_mapping(monkeypatch):
    """Change the mapping and the sentence changes with it, or it is not derived."""
    from letter import config
    before = config.pm_format_summary()
    monkeypatch.setitem(config.FORMAT_FOR_DAY, "monday", "recap")
    after = config.pm_format_summary()
    assert before != after
    assert "Mon/Tue/Wed/Thu the shorter recap" in after or "Mon" in after


def test_the_summary_names_every_format_in_use():
    from letter import config
    summary = config.pm_format_summary()
    for kind in set(config.FORMAT_FOR_DAY.values()):
        assert config.FORMAT_LABELS[kind] in summary, kind


# -- Which cash block each evening letter carries ------------------------------

_CASH_WTD = {"regions": {
    "NE": {"live_low": 221.0, "live_high": 222.5, "dressed_low": 348.0, "dressed_high": 350.0},
    "IA/MN": {"live_low": 218.0, "live_high": 222.0},
    "TX/OK/NM": {"undefined": True},
}}


def _cash_ctx(kind):
    ctx = _pm_ctx({"headlines": ["x"], "market_action": ["x"], "technicals": ["x"],
                   "technicals_lc": ["x"], "technicals_fc": ["x"], "fundamental": ["x"]},
                  kind=kind)
    ctx["regional_cash"] = _CASH_WTD
    ctx["cutout"] = {"choice": {"value": 377.31, "change": -1.58},
                     "select": {"value": 352.34, "change": -5.51}}
    ctx["daily_slaughter"] = {"current_day": 94000, "wtd": 299000}
    return ctx


def test_monday_still_reports_last_weeks_cash():
    """
    On a Monday the week that just closed is the week worth reporting, so the
    full letter keeps the weighted average. Ross confirmed this one is right.
    """
    html = render.build_html(_cash_ctx("tuesday"))
    assert "Last week" in html and "cash trade" in html


def test_the_recap_reports_the_week_in_progress():
    """Tuesday onward, last week's average is history; this week is the news."""
    html = render.build_html(_cash_ctx("recap"))
    assert "<h2>Cash Trade</h2>" in html
    assert "Last week" not in html
    assert "221-222.50 live" in html


def test_the_recap_cash_block_repeats_nothing_from_the_rundown():
    """
    Ross's reason for trimming it: the cutout and the slaughter counts are a few
    inches below in the rundown on this letter, so carrying them here too is the
    same figure twice on one page. The morning brief has no rundown, which is
    why it keeps them.
    """
    html = render.build_html(_cash_ctx("recap"))
    cash = html.split("<h2>Cash Trade</h2>")[1].split("<h2>")[0]
    assert "Cutout" not in cash
    assert "Slaughter" not in cash
    # ...and they are still on the letter, lower down
    assert "Cattle market rundown" in html


def test_an_undefined_state_is_left_out_rather_than_listed():
    """Naming four states so three can say Undefined is three wasted lines."""
    html = render.build_html(_cash_ctx("recap"))
    cash = html.split("<h2>Cash Trade</h2>")[1].split("<h2>")[0]
    assert "NE:" in cash and "IA/MN:" in cash
    assert "TX/OK/NM" not in cash


def test_the_morning_brief_and_the_recap_share_one_implementation():
    """
    Two ways of writing "how this letter formats a cash range" is exactly the
    pair that drifts. The rows come from one function.
    """
    rows = render.wtd_cash_rows({"regional_cash": _CASH_WTD})
    assert rows == ["NE: 221-222.50 live &middot; 348-350 dressed",
                    "IA/MN: 218-222 live"]
    src = (REPO_ROOT / "letter" / "render.py").read_text(encoding="utf-8")
    assert src.count("No established test this week") == 1


def test_the_recap_actually_fetches_week_to_date_cash():
    """
    The block renders nothing without it, and gather only pulled it for the AM
    and Friday. Friday's is a DIFFERENT source -- a single day, North/South --
    so the recap needs the week-to-date one by name.
    """
    src = (REPO_ROOT / "letter" / "build.py").read_text(encoding="utf-8")
    recap = src[src.index('if kind == "recap":'):src.index('if kind == "friday":')]
    assert "fetch_regional_cash_wtd" in recap


def test_friday_uses_the_same_cash_block_as_the_recap():
    """
    Changed 2026-09-24 at Ross's request. Friday used to print North/South for a
    SINGLE DAY -- the Friday itself -- under a letter reviewing the week. It now
    prints the week by state, which is the week the letter is about.
    """
    ctx = _cash_ctx("friday")
    ctx["commentary"] = {"key_headlines": ["x"], "cash_recap": ["y"]}
    html = render.build_html(ctx)
    assert "<h2>Cash Trade</h2>" in html
    assert "221-222.50 live" in html
    # the written recap section is separate and still there
    assert "Cash Trade Recap" in html


def test_a_region_with_no_test_all_week_is_omitted_on_friday():
    """
    THE COST OF SHARING THE BLOCK, recorded rather than hidden. The old Friday
    block printed "South: Undefined" -- USDA's own answer for too little
    confirmed trade. The shared block omits a region that did not trade, because
    on a daily letter naming four so three can say Undefined is wasted lines.

    On a WEEKLY letter that is arguably news: a region that never established a
    test all week is a fact. Flagged to Ross; if he wants it back, the block
    takes a flag rather than a second copy.
    """
    ctx = _cash_ctx("friday")
    ctx["commentary"] = {"key_headlines": ["x"]}
    html = render.build_html(ctx)
    cash = html.split("<h2>Cash Trade</h2>")[1].split("<h2>")[0]
    assert "TX/OK/NM" not in cash
    assert "Undefined" not in cash


def test_friday_fetches_the_week_not_the_day():
    src = (REPO_ROOT / "letter" / "build.py").read_text(encoding="utf-8")
    friday = src[src.index('if kind == "friday":'):]
    friday = friday[:friday.index("return ctx")]
    assert "fetch_regional_cash_wtd" in friday
    assert "fetch_regional_cash(issue)" not in friday


# -- Comments ------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["tuesday", "recap", "friday"])
def test_every_evening_letter_has_comments_last(kind):
    """
    Ross's catch-all, added 2026-09-24: whatever the named sections do not
    cover. Last in the list, because the list is the order they render in.
    """
    keys = [k for k, _ in commentary.sections_for(kind)]
    assert keys[-1] == "comments", keys


def test_the_morning_brief_does_not_get_comments():
    """
    One page and under three minutes is the brief's whole budget, and a
    free-text catch-all is the easiest way to spend it.
    """
    assert "comments" not in dict(commentary.sections_for("am"))


@pytest.mark.parametrize("kind", ["tuesday", "recap", "friday"])
def test_comments_render_above_the_sign_off(kind):
    """
    "Below the cattle market rundown and above Have a good evening." The three
    formats end with different blocks -- Friday's rundown sits mid-letter -- so
    the position that means the same thing in all three is last before the
    sign-off.
    """
    ctx = _cash_ctx(kind)
    ctx["commentary"] = {"headlines": ["x"], "market_action": ["x"], "technicals": ["x"],
                         "technicals_lc": ["x"], "technicals_fc": ["x"],
                         "fundamental": ["x"], "key_headlines": ["x"], "cash_recap": ["x"],
                         "comments": ["Feedlots are current."]}
    html = render.build_html(ctx)
    assert "<h2>Comments</h2>" in html
    assert html.index("<h2>Comments</h2>") < html.index('class="signoff"')
    # nothing else comes between it and the sign-off
    assert "<h2>" not in html[html.index("<h2>Comments</h2>") + 20:html.index('class="signoff"')]


def test_on_the_recap_comments_sit_directly_under_the_rundown():
    """Which is how Ross described the position."""
    ctx = _cash_ctx("recap")
    ctx["commentary"] = {"headlines": ["x"], "market_action": ["x"],
                         "technicals": ["x"], "comments": ["Feedlots are current."]}
    import re as _re
    heads = _re.findall(r"<h2>(.*?)</h2>", render.build_html(ctx))
    assert heads[-2:] == ["Cattle market rundown:", "Comments"]


def test_empty_comments_print_no_heading():
    """Same rule as every other section: blank means absent, not empty."""
    ctx = _cash_ctx("recap")
    ctx["commentary"] = {"market_action": ["x"], "comments": []}
    assert "Comments" not in render.build_html(ctx)


# -- Which change each letter quotes -------------------------------------------

@pytest.mark.parametrize("kind,expected", [
    ("am", "day"), ("tuesday", "day"), ("recap", "day"), ("friday", "week"),
])
def test_only_friday_quotes_the_week(kind, expected):
    """
    Narrowed 2026-09-24. The week-in-review is the letter that reports a week;
    Monday through Thursday quote the prior session like the morning brief.

    DELIBERATE DEPARTURE, NOT A BUG FIX. config.py records that the 9/22 letter
    -- a MONDAY -- quoted week-over-week on all six contracts, exact to the
    thousandth. Ross asked for this twice and explicitly.
    """
    from letter import config
    assert config.change_basis_for(kind) == expected


def test_an_unknown_format_cannot_render_a_gap():
    """
    change_week needs the prior FRIDAY'S settle and prints [[?]] without it;
    change_day needs only the previous bar. The fallback is the safe one.
    """
    from letter import config
    assert config.change_basis_for("something new") == "day"


def test_monday_to_thursday_print_a_real_change_without_a_week_base():
    """
    The nuisance this retires. Massive has had no prior-Friday bar since
    2026-09-14, so these letters printed [[?]] wherever the hand-typed
    substitute was missing -- which is every reboot of the deployed app.
    """
    rows = [{"month": "Oct", "settle": 219.075, "change_day": -1.85,
             "change_week": None, "week_base_missing": True}]
    for kind in ("tuesday", "recap"):
        from letter import config
        html = render.futures_block("Live Cattle", rows, config.change_basis_for(kind))
        assert "-1.85" in html
        assert render.MISSING not in html


def test_friday_still_depends_on_the_week_base():
    """Correctly -- it is the letter reporting a week. Marked, never guessed."""
    from letter import config
    rows = [{"month": "Oct", "settle": 219.075, "change_day": -1.85,
             "change_week": None, "week_base_missing": True}]
    html = render.futures_block("Live Cattle", rows, config.change_basis_for("friday"))
    assert render.MISSING in html


def test_the_basis_comes_from_the_format_not_the_cache():
    """
    data_<slug>_<date>.json stores the basis in force when it was fetched, so
    every file written before 2026-09-24 says "week". A --no-fetch re-render
    would quote week-over-week on a Monday and print [[?]] for it.
    """
    build_src = (REPO_ROOT / "letter" / "build.py").read_text(encoding="utf-8")
    page_src = (REPO_ROOT / "apps" / "weekly_reports" / "app.py").read_text(encoding="utf-8")
    assert 'ctx["change_basis"] = config.change_basis_for(kind)' in build_src
    assert 'ctx_for_render["change_basis"] = config.change_basis_for(kind)' in page_src
