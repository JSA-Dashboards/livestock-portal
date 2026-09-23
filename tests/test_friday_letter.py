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

from letter import cof, commentary, render, sources


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

def test_the_two_letters_have_different_sections():
    tue = dict(commentary.sections_for("tuesday"))
    fri = dict(commentary.sections_for("friday"))
    assert "market_action" in tue and "market_action" not in fri
    assert "fundamental" in tue and "fundamental" not in fri
    assert "key_headlines" in fri and "cash_recap" in fri and "cof_note" in fri
    # Shared on purpose: a technical read means the same thing in both.
    assert "technicals_lc" in tue and "technicals_lc" in fri


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
    technicals.build() returns int keys; the context is cached to JSON between
    the fetch run and the --no-fetch re-render, and JSON has no integer keys.
    Looking up only the int made the moving averages vanish from the re-rendered
    letter with no error at all.
    """
    import json
    tech = {"month": "Oct", "ma": {9: 216.392, 20: 215.216}}
    fresh = render.technicals_block(tech, [], "Live Cattle")
    reloaded = render.technicals_block(json.loads(json.dumps(tech)), [], "Live Cattle")
    assert "216.392" in fresh and "215.216" in fresh
    assert reloaded == fresh


# -- Futures data integrity ---------------------------------------------------

def test_session_gaps_ignores_a_single_holiday_but_reports_a_run():
    """
    2026-09-07 was Labor Day and the series steps 09-04 to 09-08 -- one missing
    weekday, not a fault. The 09-14..09-18 hole is five, and it silently
    corrupted both the weekly change and the moving averages.
    """
    import pandas as pd
    holiday = pd.to_datetime(["2026-09-04", "2026-09-08", "2026-09-09"]).date
    assert sources.session_gaps(list(holiday), date(2026, 9, 4), date(2026, 9, 9)) == []

    gapped = pd.to_datetime(["2026-09-11", "2026-09-21", "2026-09-22"]).date
    found = sources.session_gaps(list(gapped), date(2026, 9, 11), date(2026, 9, 22))
    assert date(2026, 9, 14) in found and date(2026, 9, 18) in found
    assert len(found) == 5


def test_gapped_technicals_mark_the_averages_rather_than_print_them():
    """
    A 9-day mean over a series missing a week read 216.392 where the letter's
    own figure was 218.90. Wrong, not approximate -- so it is marked.
    """
    tech = {"month": "Oct", "ma": {9: 216.392, 20: 215.216},
            "complete": False, "gaps": ["2026-09-14"]}
    html = render.technicals_block(tech, [], "Live Cattle")
    assert render.MISSING in html
    assert "216.392" not in html


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

def test_only_friday_uses_the_week_in_review_format():
    """
    Five days to pick from, two formats. Friday is the week-in-review; every
    other weekday produces the standard letter, unchanged.
    """
    from letter import config
    assert config.format_for("friday") == "friday"
    for d in ("monday", "tuesday", "wednesday", "thursday"):
        assert config.format_for(d) == "tuesday", d
    assert config.format_for("nonsense") == "tuesday"


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
    "Dec Corn -8'6 at 528" -- month before the commodity, change before the
    price, joined by "at". The same shape the evening letter uses for cattle.
    """
    html = render.am_blocks(
        {"outside": [{"label": "Corn", "month": "Dec", "style": "eighths",
                      "price": 528.0, "change": -8.75}]}, {})
    assert "Dec Corn -8'6 at 528" in "".join(html).replace("&nbsp;", " ")


def test_fci_heading_and_no_second_date():
    """The heading says Estimate and the brief is dated at the top; a date on
    the value line is one more thing to read past."""
    html = "".join(render.am_blocks(
        {"fci": {"value": 336.98, "date": "2026-09-22", "change": -1.76}}, {}))
    assert "JSA FCI Estimate" in html
    assert "2026-09-22" not in html
    # Same "change at price" shape as the overnight quotes.
    assert "-1.76 at 336.98" in html.replace("&nbsp;", " ")


def test_am_collapses_two_undefined_cash_regions_into_one_line():
    """Two lines saying "Undefined" is two lines saying nothing."""
    ctx = {"regional_cash": {"regions": {
        "North": {"undefined": True}, "South": {"undefined": True}}}}
    joined = "".join(render.am_blocks(ctx, {}))
    assert "Cash: no established test" in joined
    assert "Cash North" not in joined


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
    """Adding a third publication should be one line."""
    from letter import mailbox
    labels = {d["label"] for d in mailbox.DIGESTS}
    assert labels == {"Meatingplace", "eMeat", "Global AgriTrends", "Sterling"}
    assert all("match" in d for d in mailbox.DIGESTS)
