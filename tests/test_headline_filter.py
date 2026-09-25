"""
The headline candidate panel's relevance filter and the packer search parser.

WHY THIS FILE EXISTS. On 2026-09-23 an ICE operation in Kansas had meatpacking
plants delaying shifts. It ran on KMUW and across the Kansas public stations,
and the panel never offered it -- twice over. No source reached a local
newsroom, AND the title matched not one word of the relevance filter, so even
with the right feed it would have been dropped as agronomy.

The filter is the half that can regress silently: it is one regex, tightening it
against noise is a normal thing to want to do, and nothing about a headline that
never appears says it was rejected. Every MUST_PASS case below is a real
headline this panel is for. Every MUST_REJECT case is a real one it returned
while the plant words were still too loose.

    python -m pytest tests/test_headline_filter.py -q

Offline by design -- no test here touches Google News. What the search returns
tomorrow is not a property of this code.
"""
from __future__ import annotations

import pytest

from letter import headlines


# Real titles, all of them cattle news a reader of the letter would want.
MUST_PASS = [
    # The miss itself. Contains no company name and no word from the original
    # list -- "meatpacking", not "packer". This is the case to keep passing.
    "ICE agents in Kansas cause schools to warn families and meatpacking plants"
    " to delay shifts",
    "After ICE sweeps Kansas, schools warn families of detentions and a"
    " meatpacking plant delays shifts",
    "Illinois seeks buyer for Tyson Foods beef plant",
    "Tyson Joslin Closure Reshapes Local Cattle Market",
    "Agristar meat processing plant rehiring after fire",
    "Harmon, Halpin support Joslin following Tyson Foods facility closure",
    "JBS lifts Greeley kill",
    "Cargill idles a shift",
    "National Beef confirms the schedule",
    "Packing plant workers walk out",
]

# Also real, and all returned by the packer search before the plant phrases
# required a meat qualifier. A bare "processing plant" is not a cattle story.
MUST_REJECT = [
    "USPS Announces Major Upgrades for Sioux Falls Processing Plant",
    "Leroy: to close Hitra processing plant after December",
    "'Unique smell': Firefighters respond to blaze at Calgary processing plant",
    "See photos, videos of Blueridge Processing plant in McDowell County",
    # The agronomy the filter has always existed to keep out. A widened packer
    # vocabulary must not let these back in.
    "Farmers plant record corn acres",
    "Plant disease pressure builds across the eastern Corn Belt",
    "Planting intentions shift toward soybeans",
]


@pytest.mark.parametrize("title", MUST_PASS)
def test_relevant_accepts(title):
    assert headlines._RELEVANT.search(title), f"dropped a cattle story: {title}"


@pytest.mark.parametrize("title", MUST_REJECT)
def test_relevant_rejects(title):
    assert not headlines._RELEVANT.search(title), f"let noise through: {title}"


def test_clean_unescapes_entities():
    """Titles arrive escaped; "Tyson&#39;s" must not reach the Headlines box."""
    assert headlines._clean("Tyson&#39;s Joslin plant") == "Tyson's Joslin plant"
    assert headlines._clean("beef &amp; pork") == "beef & pork"


def test_clean_strips_tags_before_unescaping():
    """Order matters: escaped markup is text, real markup is not."""
    assert headlines._clean("<b>beef</b> &lt;b&gt;plant&lt;/b&gt;") == "beef <b>plant</b>"


def test_dedupe_collapses_reprints_not_rewrites():
    """
    The same headline from two outlets is one row; the same STORY written twice
    is two. Dropping a story is the failure this whole change is about, so the
    match is deliberately exact once case and punctuation are gone.
    """
    items = [
        {"title": "Illinois seeks buyer for Tyson Foods beef plant"},
        {"title": "ILLINOIS SEEKS BUYER FOR TYSON FOODS BEEF PLANT!"},
        {"title": "State of Illinois ready to assist Joslin beef plant buyer"},
    ]
    out = headlines._dedupe(items)
    assert len(out) == 2
    assert out[0]["title"] == "Illinois seeks buyer for Tyson Foods beef plant"


def test_dedupe_drops_untitled_rows():
    assert headlines._dedupe([{"title": ""}, {"title": "   "}, {}]) == []


def test_a_200_that_is_not_a_feed_is_reported(monkeypatch):
    """
    The failure that actually happened. Google answers a datacenter IP with a
    consent page -- HTTP 200, no <item> anywhere -- and before this the panel
    lost a whole source without one word on screen, which is indistinguishable
    from a quiet news day.
    """
    class _Resp:
        status_code = 200
        text = "<html><body>Before you continue to Google News</body></html>"

    monkeypatch.setattr(headlines.sources, "_session",
                        lambda *a, **k: type("S", (), {"get": lambda *a, **k: _Resp()})())
    rows = headlines.fetch_packer_news()
    assert rows, "a consent page must not come back as silence"
    assert all(r.get("error") for r in rows)
    assert "no feed" in rows[0]["error"]


def test_an_empty_but_real_feed_is_not_an_error(monkeypatch):
    """A feed that parses and simply has nothing relevant is a quiet morning."""
    class _Resp:
        status_code = 200
        text = ("<rss><channel><item><title>Corn basis firms - AgWeb</title>"
                "<source url='x'>AgWeb</source></item></channel></rss>")

    monkeypatch.setattr(headlines.sources, "_session",
                        lambda *a, **k: type("S", (), {"get": lambda *a, **k: _Resp()})())
    assert headlines.fetch_packer_news() == []


# -- Reuters / Politico / WSJ / NYT -------------------------------------------
# Added 2026-09-24. These four have no cattle desk, so the subject filter has to
# be stricter than the one an ag feed needs. Every case below is a real result
# from the live query.

NEWSROOM_PASS = [
    "Trump officials weigh rolling back beef import plan as GOP midterm panic spreads",
    "US eases screwworm ban on Mexican cattle, but beef prices unlikely to budge",
    "Brazil to use Uruguay's surplus of beef export quota to China, Lula says",
    "Tyson Foods Reports Higher Profit as Sales Tick Up",
    "Ranchers press Congress over cattle imports",
]

NEWSROOM_REJECT = [
    # Bare "beef" is slang. This one passes the ordinary feed filter, which is
    # the whole reason _NEWSROOM exists.
    "Seahawks' Mike Macdonald, Broncos' Sean Payton squash beef after 'Cold War' video",
    # Bare "export" carries a cattle story in a farm feed and nothing here.
    "China's clean tech exports avoided more CO2 than UK emitted last year",
    "The NYC Marathon Route Is Changing. Here's What's Different.",
    "We Put 8 Vegetarian Sandwiches Head-to-Head",
    "POLITICO barred from White House after court ruling restoring access",
    "Venezuela's Rodriguez promises elections in transition to 'full democracy'",
]


@pytest.mark.parametrize("title", NEWSROOM_PASS)
def test_newsroom_filter_accepts(title):
    assert headlines._NEWSROOM.search(title), f"dropped a cattle story: {title}"


@pytest.mark.parametrize("title", NEWSROOM_REJECT)
def test_newsroom_filter_rejects(title):
    assert not headlines._NEWSROOM.search(title), f"let noise through: {title}"


def test_the_loose_filter_would_have_let_the_sports_beef_through():
    """Pins WHY there are two filters, so nobody collapses them back into one."""
    sports = NEWSROOM_REJECT[0]
    assert headlines._RELEVANT.search(sports)          # the ag-feed filter passes it
    assert not headlines._NEWSROOM.search(sports)      # the newsroom filter does not


def test_a_ticker_page_is_not_a_story():
    """
    Matches every content test there is and is the publisher's quote widget.
    Turns up on every run of the WSJ query.
    """
    assert headlines._NOT_A_STORY.search("Tyson Foods Inc. Cl A (TSN) Stock Price Today")
    assert not headlines._NOT_A_STORY.search("Tyson Foods Reports Higher Profit as Sales Tick Up")


# -- Drovers and Beef Magazine -------------------------------------------------

def test_the_trade_sites_are_scanned():
    for site in ("drovers.com", "beefmagazine.com"):
        assert f"site:{site}" in headlines.TRADE_NEWS_QUERY


def test_drovers_is_reached_without_touching_drovers():
    """
    The reason this is a search and not a feed: the module docstring records
    that Drovers 403s anything that is not a browser. Google indexes them, so
    their reporting is reachable with no request to their server.
    """
    src = (__import__("pathlib").Path(headlines.__file__)).read_text(encoding="utf-8")
    assert "drovers.com" in src
    # no direct feed was added alongside it
    assert not any("drovers" in url.lower() for _, url in headlines.RSS_FEEDS)


def test_the_trade_press_uses_the_LOOSE_filter():
    """
    Run through _NEWSROOM, a real Drovers headline is discarded: that filter has
    no word for "calf" because a general newsroom never needed one. Trade press
    does not need disambiguating -- every story is already a cattle story.
    """
    real = "Fall Calf Run Begins as Prices Ease, Herd Rebuilding Slow"
    assert headlines._RELEVANT.search(real)
    assert not headlines._NEWSROOM.search(real)

    src = (__import__("pathlib").Path(headlines.__file__)).read_text(encoding="utf-8")
    call = src[src.index("def fetch_trade_news"):src.index("def fetch_trade_news") + 400]
    assert "_RELEVANT" in call and "_NEWSROOM" not in call


def test_beef_magazine_has_two_roads_on_purpose():
    """
    It is the only entry in RSS_FEEDS, so that feed is a single point of failure.
    The search is a second route to the same publisher; _dedupe collapses the
    overlap when both answer.
    """
    assert any("beefmagazine" in url for _, url in headlines.RSS_FEEDS)
    assert "site:beefmagazine.com" in headlines.TRADE_NEWS_QUERY
    both = headlines._dedupe([
        {"title": "Export ban rumors quelled—for now", "source": "Beef Magazine"},
        {"title": "Export ban rumors quelled—for now", "source": "beefmagazine.com"},
    ])
    assert len(both) == 1


def test_all_four_newsrooms_are_in_the_query():
    for site in ("reuters.com", "politico.com", "wsj.com", "nytimes.com"):
        assert f"site:{site}" in headlines.GENERAL_NEWS_QUERY


def test_the_newsroom_search_is_one_request():
    """Four separate searches would be four round trips on a button Ross waits on."""
    assert headlines.GENERAL_NEWS_QUERY.count("site:") == len(headlines.GENERAL_NEWS_SITES)


def test_the_pick_list_never_writes_to_a_checkbox_key():
    """
    The Add button crashed the page on its first real use, 2026-09-24:
    StreamlitWidgetAlreadyInstantiatedError, because it reset the checkboxes by
    assigning st.session_state["head_<n>"] = False after those checkboxes had
    already been built in the same run.

    The fix puts a generation number in the key and bumps it, so the next run
    asks for widgets that have never existed. Read as text -- importing the page
    would execute a Streamlit script.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "apps" / "weekly_reports" / "app.py").read_text(encoding="utf-8")

    assert 'st.session_state[f"head_' not in src, \
        "assigning to a checkbox's own key is what raised the error"
    assert "wcr_head_gen" in src, "the generation counter is how the ticks get cleared"

    # The text area IS written to, and that is fine: the panel renders above the
    # boxes precisely so wcr_<section> does not exist yet. Guard the ordering.
    assert src.index("wcr_head_gen") < src.index('key=f"wcr_{key}"'), \
        "the candidate panel must stay above the commentary text areas"


def test_packer_queries_are_all_qualified():
    """
    Every query names a packer or a plant AND a cattle word. "Tyson" alone is a
    boxer and a chicken company; "packing plant" alone is a cardboard factory.
    """
    for label, query in headlines.PACKER_QUERIES:
        assert any(w in query.lower() for w in ("beef", "cattle", "slaughter")), label


# -- Newest first --------------------------------------------------------------

import datetime as _dt


def test_all_three_date_formats_parse():
    """
    The sources genuinely differ and every one of these is real:
      ISO+tz from RSS, Google News and the mailbox; US order from AMS;
      a bare date from the border report.
    """
    iso = headlines._when_key({"when": "2026-09-24T14:27:40+00:00"})
    ams = headlines._when_key({"when": "09/24/2026 11:07:09"})
    day = headlines._when_key({"when": "2026-09-23"})
    assert iso.year == 2026 and iso.hour == 14
    assert ams.month == 9 and ams.day == 24 and ams.hour == 11
    assert day.day == 23 and day.hour == 0
    for got in (iso, ams, day):
        assert got.tzinfo is not None, "naive stamps must be pinned to UTC to sort"


def test_an_unknown_date_sorts_to_the_bottom():
    """An item whose age is unknown must not claim to be the newest on the page."""
    assert headlines._when_key({"when": None}) == headlines._EPOCH
    assert headlines._when_key({"when": "not a date"}) == headlines._EPOCH
    assert headlines._when_key({}) == headlines._EPOCH


def test_candidates_come_back_newest_first(monkeypatch):
    monkeypatch.setattr(headlines, "fetch_usda_narratives", lambda *a, **k: [
        {"source": "USDA AMS cash trade", "title": "AMS narrative", "when": "09/22/2026 11:07:09"}])
    monkeypatch.setattr(headlines, "fetch_rss", lambda *a, **k: [
        {"source": "Beef Magazine", "title": "older story", "when": "2026-09-23T08:00:00+00:00"},
        {"source": "Beef Magazine", "title": "newest story", "when": "2026-09-24T20:00:00+00:00"}])
    monkeypatch.setattr(headlines, "fetch_packer_news", lambda *a, **k: [])
    monkeypatch.setattr(headlines, "fetch_trade_news", lambda *a, **k: [])
    monkeypatch.setattr(headlines, "fetch_general_news", lambda *a, **k: [])
    got = headlines.candidates(include_mailbox=False)
    assert [i["title"] for i in got["items"]] == ["newest story", "older story", "AMS narrative"]


def test_ordering_does_not_decide_which_duplicate_survives(monkeypatch):
    """
    Dedupe keeps the FIRST occurrence and source order is priority order, so the
    USDA copy of a story beats a newsroom's. Sorting must run AFTER that, or the
    newer-but-lesser copy wins.
    """
    same = "Screwworm ban eased on Mexican cattle"
    monkeypatch.setattr(headlines, "fetch_usda_narratives", lambda *a, **k: [
        {"source": "USDA border report", "title": same, "when": "2026-09-20"}])
    monkeypatch.setattr(headlines, "fetch_rss", lambda *a, **k: [
        {"source": "Beef Magazine", "title": same, "when": "2026-09-24T20:00:00+00:00"}])
    for fn in ("fetch_packer_news", "fetch_trade_news", "fetch_general_news"):
        monkeypatch.setattr(headlines, fn, lambda *a, **k: [])
    got = headlines.candidates(include_mailbox=False)
    assert len(got["items"]) == 1
    assert got["items"][0]["source"] == "USDA border report", "the newer copy displaced the better one"


def test_equal_timestamps_keep_their_source_order(monkeypatch):
    """
    A digest gives every headline the same receivedDateTime, so ties are the
    common case, not the edge case. The sort is stable.
    """
    when = "2026-09-24T17:00:00+00:00"
    rows = [{"source": "Meatingplace", "title": f"headline {n}", "when": when} for n in range(5)]
    monkeypatch.setattr(headlines, "fetch_usda_narratives", lambda *a, **k: [])
    monkeypatch.setattr(headlines, "fetch_rss", lambda *a, **k: rows)
    for fn in ("fetch_packer_news", "fetch_trade_news", "fetch_general_news"):
        monkeypatch.setattr(headlines, fn, lambda *a, **k: [])
    got = headlines.candidates(include_mailbox=False)
    assert [i["title"] for i in got["items"]] == [f"headline {n}" for n in range(5)]


def test_the_usda_narratives_are_pinned_above_everything():
    """
    A pure time sort put them at 22 and 41 of 42 on 2026-09-24 -- not because
    they were stale, but because AMS stamps Eastern with no zone and the border
    report carries a date with no time. They are also the only two items that
    are USDA's own prose about this market rather than someone's headline.
    """
    items = [
        {"title": "brand new wire story", "when": "2026-09-24T23:00:00+00:00"},
        {"title": "AMS narrative", "when": "09/22/2026 11:07:09", "pinned": True},
        {"title": "older wire story", "when": "2026-09-24T09:00:00+00:00"},
        {"title": "border narrative", "when": "2026-09-21", "pinned": True},
    ]
    ordered = sorted(headlines._dedupe(items),
                     key=lambda i: (bool(i.get("pinned")), headlines._when_key(i)),
                     reverse=True)
    assert [i["title"] for i in ordered] == [
        "AMS narrative",          # pinned, and the newer of the two pins
        "border narrative",
        "brand new wire story",   # then everything else, newest first
        "older wire story",
    ]


def test_the_pin_is_set_at_the_source_not_matched_on_the_name():
    """
    An outlet called "USDA Reports Weekly" arriving from a news search must not
    pin itself to the top of the panel. Only fetch_usda_narratives sets the flag.
    """
    src = (__import__("pathlib").Path(headlines.__file__)).read_text(encoding="utf-8")
    narratives = src[src.index("def fetch_usda_narratives"):src.index("def candidates")]
    assert narratives.count('"pinned": True') == 2, "both USDA rows must carry the flag"

    ordering = src[src.index("ordered = sorted"):src.index("ordered = sorted") + 200]
    assert 'i.get("pinned")' in ordering
    assert "USDA" not in ordering, "the sort must not match on the source name"

    # an impostor from a search carries no flag and sorts by time like anything else
    impostor = {"source": "USDA Reports Weekly", "title": "x", "when": "2020-01-01"}
    assert not impostor.get("pinned")


def test_candidates_puts_the_pinned_rows_first(monkeypatch):
    monkeypatch.setattr(headlines, "fetch_usda_narratives", lambda *a, **k: [
        {"source": "USDA AMS cash trade", "title": "AMS prose",
         "when": "09/20/2026 11:07:09", "pinned": True}])
    monkeypatch.setattr(headlines, "fetch_rss", lambda *a, **k: [
        {"source": "Beef Magazine", "title": "much newer", "when": "2026-09-24T22:00:00+00:00"}])
    for fn in ("fetch_packer_news", "fetch_trade_news", "fetch_general_news"):
        monkeypatch.setattr(headlines, fn, lambda *a, **k: [])
    got = headlines.candidates(include_mailbox=False)
    assert [i["title"] for i in got["items"]] == ["AMS prose", "much newer"]
