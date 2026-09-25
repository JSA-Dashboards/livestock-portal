"""
The Graph query that reads the four subscription digests.

WHY THIS FILE EXISTS. Admin consent landed 2026-09-24 and the mailbox worked
for the first time -- at which point all four sources returned HTTP 400. The
code had been written months earlier and never once run against Graph, because
sign-in was blocked, so the panel said "mailbox not connected" and nobody could
tell the difference between not-signed-in and a query Graph would always reject.

TWO TRAPS, ONE OF THEM SILENT, and both are pinned below.

  InefficientFilter   Graph refuses $filter on from/emailAddress together with
                      $orderby receivedDateTime. 400, every request, loudly.

  Oldest first        The obvious fix -- drop the $orderby -- is worse, because
                      the default order on /me/messages is OLDEST FIRST. A bare
                      sender filter returned Sterling from 2025-12-16 and
                      Meatingplace from 2026-08-26; every one outside the age
                      window, so every source would report "nothing recent",
                      for ever, while the digests arrived daily.

The date clause does both jobs: legal beside a sender filter, and it bounds the
result to the window so the client-side newest-pick has what it needs.

    python -m pytest tests/test_mailbox.py -q

Offline -- these read the source and exercise the parser. Nothing touches Graph.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from letter import mailbox

REPO = Path(__file__).resolve().parent.parent
SRC = (REPO / "letter" / "mailbox.py").read_text(encoding="utf-8")


# -- The query shape -----------------------------------------------------------

def test_no_orderby_on_a_sender_filter():
    """
    Graph answers 400 InefficientFilter to that combination, every time.

    Checks for the query KEY, not the word -- the word appears several times in
    the comment above the query explaining why it is not there.
    """
    import re
    assert not re.search(r'"\$orderby"\s*:', SRC), \
        "$orderby beside a sender filter is a hard 400"


def test_the_filter_carries_a_date_clause():
    """
    Without it the query is legal and silently useless -- oldest first, so the
    age check downstream rejects everything and every source reads as quiet.
    """
    assert "receivedDateTime ge" in SRC
    assert "since_iso" in SRC


def test_the_window_comes_from_the_caller():
    """max_age_h is the panel's window; the query must not invent its own."""
    assert 'since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")' in SRC
    assert "timedelta(hours=max_age_h)" in SRC


def test_top_is_generous_enough_to_hold_a_window():
    """
    Ordering is not guaranteed, so the newest is picked client-side -- which
    only works if the window's messages actually came back. $top 5 was fine
    with an $orderby and is not without one.
    """
    import re
    # The DIGEST query only. _never_matched uses $top 1 deliberately -- it is an
    # existence check and wants one row or none.
    block = SRC[SRC.index("fields = "):SRC.index("try:", SRC.index("fields = "))]
    tops = {int(m) for m in re.findall(r'"\$top": (\d+)', block)}
    assert tops and min(tops) >= 25, f"$top too small without an $orderby: {tops}"


def test_the_newest_is_picked_rather_than_assumed():
    """The code must compare dates, not trust the order Graph returned."""
    assert "if newest is None or when > newest[0]" in SRC


# -- What counts as a headline -------------------------------------------------

@pytest.mark.parametrize("junk", [
    # Every one of these was offered to Ross as a cattle headline on 2026-09-24,
    # the first day real messages came through.
    "newsletters@newsletter.meatingplace.com",
    "https://emeat.io/dashboard/tables",
    "Customize your Daily Bulletin",
    "Update your email preferences",
])
def test_real_chrome_is_dropped(junk):
    assert mailbox.parse_headlines(junk, "text") == [], junk


@pytest.mark.parametrize("real", [
    "ICE Activity in Kansas Affects National Beef Production: Report",
    "Feedlot Losses Widen as Packers Remain Profitable",
    "Nunn introduces bill to suspend Trump's beef imports, bolster US herd",
    "Sterling UPDATE - Profit Trackers - Sept. 21, 2026",
])
def test_real_headlines_survive(real):
    """All four are genuine digest subjects from the same morning."""
    assert mailbox.parse_headlines(real, "text") == [real], real


def test_a_url_inside_a_sentence_is_not_a_bare_link():
    """
    The bare-link rule is one token with an @ or a scheme. A headline that
    happens to mention a domain is still a headline.
    """
    line = "Tyson to close its Joslin plant, see tyson.com for the statement"
    assert mailbox.parse_headlines(line, "text") == [line]


def test_an_address_with_spaces_around_it_still_goes():
    """Chrome wins over the bare-link rule; neither should let this through."""
    assert mailbox.parse_headlines("Contact us at news@example.com today", "text") == []


# -- The wrong address that hid as a quiet publisher ---------------------------

def test_global_agritrends_sends_from_agritrends_dot_com():
    """
    It was configured as globalagritrends.com and matched nothing from the day
    this module was written until 2026-09-25. The real sender is agritrends.com.
    """
    gat = next(d for d in mailbox.DIGESTS if d["label"] == "Global AgriTrends")
    assert gat["sender"] == "no-reply@agritrends.com"
    assert "globalagritrends" not in gat["sender"]


def test_only_the_no_reply_address_counts():
    """
    bstuart@agritrends.com is a person at the same firm who replies about price
    moves. Matching the domain would put that correspondence in the panel.
    """
    gat = next(d for d in mailbox.DIGESTS if d["label"] == "Global AgriTrends")
    assert gat["sender"].startswith("no-reply@")


def test_a_matcher_that_never_matches_is_reported_differently(monkeypatch):
    """
    THE WHOLE POINT. An exact sender filter that is wrong returns zero rows --
    the same answer a publisher who did not write today gives. "Nothing in the
    last 72h" was on screen daily for months while the address was wrong.
    """
    class _Resp:
        status_code = 200
        def json(self):
            return {"value": []}

    monkeypatch.setattr(mailbox, "token", lambda interactive=False: ("tok", None))
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
    monkeypatch.setattr(mailbox, "DIGESTS", [{"label": "Ghost", "sender": "nope@example.com"}])

    got = mailbox.fetch_digests()
    assert got["items"] == []
    assert any("NO mail from" in e and "check the address" in e for e in got["errors"]), got["errors"]


def test_a_search_matcher_gets_no_verdict():
    """
    $search is broad by nature -- zero hits says nothing about the matcher being
    wrong, so it is not accused of it.
    """
    assert mailbox._never_matched({}, {"label": "x", "match": "sterling"}) is False


# -- Chrome that reached the panel as cattle headlines -------------------------

@pytest.mark.parametrize("junk", [
    "View this email in your browser",
    "View this e-mail in your browser",
    "view in browser",
    "update subscription preferences",
    "Manage your email preferences",
    "Change preferences",
    "Customize your Daily Bulletin",
    "Update your email preferences",
])
def test_newsletter_chrome_is_dropped(junk):
    assert mailbox.parse_headlines(junk, "text") == [], junk


@pytest.mark.parametrize("real", [
    "What We're Watching: Beef & Pork Markets",
    "ALERT: Uruguay proposes to share unused beef quota",
    "China's Meat and Poultry Imports Drop -5% in August",
])
def test_agritrends_headlines_survive(real):
    """Real subjects from the digest that was invisible until today."""
    assert mailbox.parse_headlines(real, "text") == [real], real
