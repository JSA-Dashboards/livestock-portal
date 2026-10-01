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


def test_the_weight_key_does_not_leak_into_the_payload(monkeypatch):
    """`_w` is internal. It reached the page once via items[:limit]."""
    _stub(monkeypatch, [(1961, "Roger Maris breaks home run record")])
    for i in onthisday.candidates(D)["items"]:
        assert "_w" not in i
