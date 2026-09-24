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
