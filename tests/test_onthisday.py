"""
The On This Day pick list: what survives the cut, and in what order.

Two sorts do two different jobs and collapsing them breaks one of them. The
WEIGHT sort decides which facts survive `limit` -- ag over sport over US,
because that is the order of use to a cattle letter. The DISPLAY sort is
chronological with the newest first, so the oldest reads at the bottom of the
letter. Sorting by year before the cut would quietly change the selection
rather than just the order, which is the regression these pin.
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from letter import onthisday  # noqa: E402

D = dt.date(2026, 10, 1)


def _stub(monkeypatch, rows, wiki=None):
    monkeypatch.setattr(onthisday, "fetch_history_com", lambda d: list(rows))
    monkeypatch.setattr(onthisday, "fetch_wikipedia", lambda d: list(wiki or []))


def test_items_come_back_newest_first(monkeypatch):
    """Oldest at the bottom -- Ross's ask, 2026-10-01."""
    _stub(monkeypatch, [
        (1903, "Pittsburgh beats Boston in first World Series game"),
        (1961, "Roger Maris breaks home run record"),
        (1927, "Babe Ruth hits 60th homer of 1927 season"),
    ])
    years = [i["year"] for i in onthisday.candidates(D)["items"]]
    assert years == sorted(years, reverse=True), years


def test_the_weight_still_decides_what_survives_the_limit(monkeypatch):
    """
    The relevance ranking must run BEFORE the cut.

    An older agriculture item has to beat a newer non-agriculture one, or
    sorting by year has silently become the selection rule.
    """
    _stub(monkeypatch, [
        (2001, "Congress debates a highway bill"),
        (2000, "Senate passes a transport measure"),
        (1933, "Farmers organise a cattle and livestock cooperative"),
    ])
    items = onthisday.candidates(D, limit=1)["items"]
    assert len(items) == 1
    assert items[0]["year"] == 1933, "the agriculture item lost the cut to a newer one"


def test_display_order_does_not_change_the_selection(monkeypatch):
    """Both properties at once: ag survives, and the output is still descending."""
    _stub(monkeypatch, [
        (1998, "A baseball team wins the pennant"),
        (1911, "Cattle ranchers form a grazing association"),
        (1975, "The president signs a farm bill on livestock exports"),
    ])
    items = onthisday.candidates(D, limit=2)["items"]
    years = [i["year"] for i in items]
    assert years == sorted(years, reverse=True), years
    assert 1998 not in years, "a sport item displaced an agriculture one"


# October 1 as history.com actually serves it. Kept verbatim because it holds
# both halves of the problem at once: seven items a client letter must never
# print, and six it should, including the three Ross named on 2026-10-01.
OCT_1 = [
    (1864, "Confederate spy Rose O’Neal Greenhow dies"),
    (1903, "Pittsburgh beats Boston in first World Series game"),
    (1908, "Ford Motor Company unveils the Model T"),
    (1910, "A bomb explodes in the Los Angeles Times building"),
    (1924, "Jimmy Carter is born"),
    (1946, "Nazi war criminals sentenced at Nuremberg"),
    (1949, "Mao Zedong proclaims People’s Republic of China"),
    (1958, "American Express launches its first credit card"),
    (1961, "Roger Maris breaks home run record"),
    (1962, "Johnny Carson makes debut as “Tonight Show” host"),
    (1977, "Soccer star Pelé plays farewell game"),
    (1987, "Earthquake rocks Southern California"),
    (1993, "A 12-year-old girl is kidnapped, leading to California’s "
           "“three strikes” law"),
    (2005, "Suicide bombers stage attacks in Bali"),
    (2017, "Gunman opens fire on Las Vegas concert crowd, wounding hundreds "
           "and killing 58"),
]


def test_the_facts_ross_asked_for_are_admitted(monkeypatch):
    """
    Named on 2026-10-01: the Model T, Jimmy Carter, Johnny Carson.

    Each failed for a different reason -- "unveils" and "born" were not
    milestone words, and none of "Ford", "Carter" or "Tonight Show" marked the
    item as American. All three had NO tag at all, so the list was three items
    long on a day history.com offered a dozen good ones.
    """
    _stub(monkeypatch, OCT_1)
    years = [i["year"] for i in onthisday.candidates(D, limit=20)["items"]]
    for wanted in (1908, 1924, 1962):
        assert wanted in years, f"{wanted} is still being filtered out"


def test_soccer_is_not_a_sport_for_this_letter(monkeypatch):
    """
    Deliberately out, and it was briefly in.

    `soccer` went into _SPORT with the other widenings on 2026-10-01 and Ross
    took it straight back out -- this is a US cattle letter. Pele's farewell
    game is exactly the item the omission exists to drop, so it is pinned
    rather than left to the next person's judgement.
    """
    _stub(monkeypatch, OCT_1)
    years = [i["year"] for i in onthisday.candidates(D, limit=20)["items"]]
    assert 1977 not in years


@pytest.mark.parametrize("text", [
    "President Theodore Roosevelt goes on a bear hunt",
    "Abraham Lincoln delivers the Gettysburg Address",
    "Ulysses S. Grant is inaugurated as president",
    "Harry Truman addresses the nation from the Oval Office",
    "Jimmy Carter is born",
])
def test_a_president_is_reason_enough(text):
    """
    Ross's call, 2026-10-01: "US President Facts as a whole should be
    included" -- not only when the item is also a "first".
    """
    tags = onthisday._tags(text)
    assert "pres" in tags, tags
    assert onthisday._keep(text, tags)


@pytest.mark.parametrize("text", [
    "President Kennedy is assassinated in Dallas",
    "Abraham Lincoln is shot at Ford's Theatre",
    "President Garfield dies of his wounds",
])
def test_a_president_does_not_override_the_denylist(text):
    """
    The presidency is a reason to print, never a reason to ignore _GRIM.

    Assassinations are the most famous presidential anniversaries there are,
    which is exactly why this needs a test rather than an assumption.
    """
    assert not onthisday._keep(text, onthisday._tags(text))


@pytest.mark.parametrize("text", [
    "The US enacts first fugitive slave law",
    "Enslaved people are freed in the District of Columbia",
    "Japanese American internment begins",
])
def test_the_stems_cover_the_whole_word_family(text):
    """
    `slaver` matched "slavery" and NOT "slave law" -- so "The US enacts first
    fugitive slave law" cleared every filter and reached the February 12 pick
    list, tagged `US first`. Exactly the trailing-boundary mistake that let
    four atrocities through the very first version.

    It was found by spot-checking a SECOND day after a change, which is the
    habit worth keeping: one day's feed is not a test suite.
    """
    assert not onthisday._keep(text, onthisday._tags(text))


@pytest.mark.parametrize("text", [
    "A research grant is awarded to a land-grant university",
    "Bush fires sweep through New South Wales",
    "The city of Cleveland opens a new bridge",
])
def test_ordinary_words_that_are_also_presidents_do_not_tag(text):
    """
    Grant, Bush, Pierce, Taylor, Arthur, Hayes, Polk and Tyler are ordinary
    English words, and Cleveland, Wilson, Jackson and Madison are large
    American things. They need a given name or the title. Cleveland earned
    its place on that list by tagging a city bridge as presidential.
    """
    assert "pres" not in onthisday._tags(text)


def test_widening_the_allowlist_let_nothing_grim_through(monkeypatch):
    """
    THE HALF THAT MATTERS. These go to paying clients above a signature.

    The Las Vegas shooting is the specific one that got offered as an
    agriculture fact once, because the venue was called Route 91 HARVEST and
    every denylist entry carried a trailing word boundary.
    """
    _stub(monkeypatch, OCT_1)
    years = [i["year"] for i in onthisday.candidates(D, limit=20)["items"]]
    for banned in (1864, 1910, 1946, 1987, 1993, 2005, 2017):
        assert banned not in years, f"{banned} reached the pick list"


def test_a_milestone_abroad_is_still_not_a_us_fun_fact(monkeypatch):
    """
    The widened milestone list must not turn this into "anything not grim".

    Mao proclaiming the PRC and Gorbachev taking over the USSR are neither
    grim nor American, and a cattle letter has no use for them.
    """
    _stub(monkeypatch, OCT_1 + [(1988, "Mikhail Gorbachev becomes head of Soviet Union")])
    years = [i["year"] for i in onthisday.candidates(D, limit=20)["items"]]
    assert 1949 not in years
    assert 1988 not in years


def test_the_weight_key_does_not_leak_into_the_payload(monkeypatch):
    """`_w` is internal. It reached the page once via items[:limit]."""
    _stub(monkeypatch, [(1961, "Roger Maris breaks home run record")])
    for i in onthisday.candidates(D)["items"]:
        assert "_w" not in i
