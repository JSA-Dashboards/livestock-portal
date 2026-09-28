"""
Proof that mirroring the settle log MERGES rather than clobbers.

The commentary and the week base are one authored document with one writer, so
draft_store.restore()'s newest-wins is right for them. The settle log is not:
the desktop and the deployed container each build letters and each record what
they fetched, so treating it the same way would mean whichever saved last threw
away the other's days -- while looking like it had worked.

These run WITHOUT Snowflake. draft_store is faked at its boundary, so a failure
here is a logic failure rather than a connectivity one.

    python -m pytest tests/test_settle_log_sync.py -q
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from letter import draft_store, settle_log  # noqa: E402


class FakeTable:
    """The append-only table, in memory, with rows_for_kind's ordering."""

    def __init__(self, fail=False):
        self.rows = []          # (issue, kind, body, saved_at)
        self.fail = fail
        self.clock = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    def _tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def store(self, issue, kind, body, source="app"):
        if self.fail:
            return "Could not save to Snowflake: boom"
        if not (body or "").strip():
            return ""
        prior = [r for r in self.rows if r[0] == str(issue) and r[1] == kind]
        if prior and max(prior, key=lambda r: r[3])[2] == body:
            return ""
        self.rows.append((str(issue), kind, body, self._tick()))
        return ""

    def rows_for_kind(self, kind, limit=5000):
        if self.fail:
            return []
        hits = [r for r in self.rows if r[1] == kind]
        # Newest `limit` rows, handed back oldest-first -- the real one does
        # this with ORDER BY DESC + reversed(), so the fake has to drop the
        # OLDEST rows when it overflows, not the newest.
        newest = sorted(hits, key=lambda r: r[3], reverse=True)[:limit]
        return [(r[0], r[3], r[2]) for r in reversed(newest)]


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(draft_store, "enabled", lambda: True)
    monkeypatch.setattr(draft_store, "store", t.store)
    monkeypatch.setattr(draft_store, "rows_for_kind", t.rows_for_kind)
    return t


@pytest.fixture
def broken(monkeypatch):
    t = FakeTable(fail=True)
    monkeypatch.setattr(draft_store, "enabled", lambda: True)
    monkeypatch.setattr(draft_store, "store", t.store)
    monkeypatch.setattr(draft_store, "rows_for_kind", t.rows_for_kind)
    return t


def _log(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ctx(when, **tickers):
    """A build context carrying one settle per ticker for one date."""
    lc = [{"ticker": t, "settle": v, "settle_date": when}
          for t, v in tickers.items() if t.startswith("LE")]
    fc = [{"ticker": t, "settle": v, "settle_date": when}
          for t, v in tickers.items() if t.startswith("GF")]
    return {"live_cattle": lc, "feeder_cattle": fc}


# ── the merge, which is the point ────────────────────────────────────────────

def test_two_machines_union_instead_of_clobbering(table, tmp_path):
    """The desktop records Thursday, the container records Friday. Both must
    end up with both -- a whole-file newest-wins would keep one."""
    desktop = tmp_path / "desktop.json"
    cloud = tmp_path / "cloud.json"

    settle_log.record(_ctx("2026-09-24", LEZ6=221.1, GFV6=331.75), desktop, "desktop")
    settle_log.record(_ctx("2026-09-25", LEZ6=222.0, GFV6=332.5), cloud, "cloud")

    settle_log.sync(desktop)
    settle_log.sync(cloud)

    for p in (desktop, cloud):
        assert _log(p)["LEZ6"] == {"2026-09-24": 221.1, "2026-09-25": 222.0}
        assert _log(p)["GFV6"] == {"2026-09-24": 331.75, "2026-09-25": 332.5}


def test_a_partial_row_does_not_drop_the_other_product(table, tmp_path):
    """One build recorded only live cattle for a day, another only feeders.
    Folding per row would lose whichever landed first."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    settle_log.record(_ctx("2026-09-25", LEZ6=222.0), a, "a")
    settle_log.record(_ctx("2026-09-25", GFV6=332.5), b, "b")

    settle_log.sync(a)

    assert _log(a) == {"LEZ6": {"2026-09-25": 222.0}, "GFV6": {"2026-09-25": 332.5}}


def test_a_rebuild_after_the_close_corrects_the_intraday_value(table, tmp_path):
    """settle_log's own rule: last write wins for a (ticker, date)."""
    p = tmp_path / "s.json"
    settle_log.record(_ctx("2026-09-25", LEZ6=221.9), p, "morning")
    settle_log.record(_ctx("2026-09-25", LEZ6=222.0), p, "afterclose")

    p.unlink()                                   # the reboot
    settle_log.sync(p)

    assert _log(p)["LEZ6"]["2026-09-25"] == 222.0


def test_the_superseded_value_is_still_in_the_table(table, tmp_path):
    """Append-only: correcting a settle must leave the one it replaced behind,
    the same guarantee the commentary and the week base get."""
    p = tmp_path / "s.json"
    settle_log.record(_ctx("2026-09-25", LEZ6=221.9), p, "morning")
    settle_log.record(_ctx("2026-09-25", LEZ6=222.0), p, "afterclose")

    bodies = [json.loads(b) for d, _at, b in table.rows_for_kind(draft_store.SETTLE_LOG_KIND)
              if d == "2026-09-25"]

    assert [b["LEZ6"] for b in bodies] == [221.9, 222.0]


# ── the reboot ───────────────────────────────────────────────────────────────

def test_the_log_comes_back_on_a_fresh_container(table, tmp_path):
    p = tmp_path / "s.json"
    settle_log.record(_ctx("2026-09-25", LEZ6=222.0, GFV6=332.5, GFX6=328.0), p)
    assert p.exists()

    p.unlink()                                   # gitignored letter/data/ is not cloned
    msg = settle_log.sync(p)

    assert p.exists()
    assert _log(p)["GFX6"] == {"2026-09-25": 328.0}
    assert "restored from snowflake" in msg.lower()
    assert settle_log.settles_on(date(2026, 9, 25), p)["LEZ6"] == 222.0


def test_a_locally_recorded_day_is_pushed_up(table, tmp_path):
    """Recorded while Snowflake was unreachable, then pushed on the next sync."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"LEZ6": {"2026-09-22": 220.0}}), encoding="utf-8")

    msg = settle_log.sync(p)

    assert "pushed to snowflake" in msg.lower()
    assert settle_log.remote_load()["LEZ6"] == {"2026-09-22": 220.0}


def test_sync_is_quiet_when_both_sides_already_agree(table, tmp_path):
    p = tmp_path / "s.json"
    settle_log.record(_ctx("2026-09-25", LEZ6=222.0), p)
    settle_log.sync(p)

    assert settle_log.sync(p) == ""


# ── an outage must not stop the letter ───────────────────────────────────────

def test_record_still_writes_the_file_when_snowflake_is_down(broken, tmp_path):
    p = tmp_path / "s.json"
    assert settle_log.record(_ctx("2026-09-25", LEZ6=222.0), p) == 1
    assert _log(p)["LEZ6"]["2026-09-25"] == 222.0


def test_sync_reports_rather_than_raises_when_snowflake_is_down(broken, tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"LEZ6": {"2026-09-25": 222.0}}), encoding="utf-8")

    msg = settle_log.sync(p)

    assert "could not" in msg.lower()
    assert _log(p)["LEZ6"]["2026-09-25"] == 222.0        # untouched


def test_everything_is_a_no_op_when_snowflake_is_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(draft_store, "enabled", lambda: False)
    p = tmp_path / "s.json"
    settle_log.record(_ctx("2026-09-25", LEZ6=222.0), p)

    assert settle_log.sync(p) == ""
    assert _log(p)["LEZ6"]["2026-09-25"] == 222.0        # local path unchanged


# ── shape ────────────────────────────────────────────────────────────────────

def test_a_malformed_row_is_skipped_not_fatal(table, tmp_path):
    draft_store.store("2026-09-25", draft_store.SETTLE_LOG_KIND, "not json at all")
    draft_store.store("2026-09-24", draft_store.SETTLE_LOG_KIND, '{"LEZ6": 221.1}')

    assert settle_log.remote_load() == {"LEZ6": {"2026-09-24": 221.1}}


def test_the_kind_is_its_own_and_not_a_letter_format(table):
    from letter import config
    assert draft_store.SETTLE_LOG_KIND not in config.FORMAT_FOR_DAY.values()
    assert draft_store.SETTLE_LOG_KIND != draft_store.WEEK_BASE_KIND


def test_overflowing_the_row_limit_drops_the_oldest_not_the_newest(table, tmp_path):
    """A log that forgets last Friday is worse than one that forgets last year."""
    p = tmp_path / "s.json"
    for n, day in enumerate(("2026-09-21", "2026-09-22", "2026-09-23"), start=1):
        settle_log.record(_ctx(day, LEZ6=220.0 + n), p)

    kept = table.rows_for_kind(draft_store.SETTLE_LOG_KIND, limit=2)

    assert [d for d, _at, _b in kept] == ["2026-09-22", "2026-09-23"]


def test_rows_are_written_one_per_settle_date(table, tmp_path):
    p = tmp_path / "s.json"
    settle_log.record(_ctx("2026-09-24", LEZ6=221.1, GFV6=331.75), p)
    settle_log.record(_ctx("2026-09-25", LEZ6=222.0, GFV6=332.5), p)

    dates = sorted({d for d, _at, _b in table.rows_for_kind(draft_store.SETTLE_LOG_KIND)})
    assert dates == ["2026-09-24", "2026-09-25"]
