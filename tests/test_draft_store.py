"""
Proof that a draft cannot quietly disappear again.

On 2026-09-25 a nearly finished Friday letter was lost: the only copy lived in
`out/`, which a Streamlit Cloud reboot destroys. These tests pin the three
behaviours that stop that recurring, and they run WITHOUT Snowflake -- the
module is faked at the boundary, so a failure here is a logic failure rather
than a connectivity one.

  * a save appends and never overwrites, so an earlier version survives;
  * restore() keeps the NEWER of disk and Snowflake, in both directions,
    because "the database always wins" would silently eat a hand edit;
  * every entry point degrades to local-only instead of raising when
    Snowflake is unreachable -- a database outage must not stop a letter.

    python -m pytest tests/test_draft_store.py -q
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from letter import draft_store  # noqa: E402


class FakeTable:
    """The append-only table, in memory. Mirrors what the SQL actually does."""

    def __init__(self, fail=False):
        self.rows = []          # (issue, kind, body, saved_at, saved_by)
        self.fail = fail
        self.clock = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

    def _tick(self):
        self.clock += timedelta(minutes=1)
        return self.clock

    def fetch(self, issue, kind):
        if self.fail:
            return None, None
        hits = [r for r in self.rows if r[0] == str(issue) and r[1] == kind]
        if not hits:
            return None, None
        newest = max(hits, key=lambda r: r[3])
        return newest[2], newest[3]

    def store(self, issue, kind, body, source="app"):
        if self.fail:
            return "Could not save to Snowflake: boom"
        if not (body or "").strip():
            return ""
        current, _ = self.fetch(issue, kind)
        if current == body:
            return ""
        self.rows.append((str(issue), kind, body, self._tick(), source))
        return ""

    def history(self, issue, kind, limit=25):
        if self.fail:
            return []
        hits = [r for r in self.rows if r[0] == str(issue) and r[1] == kind]
        return [(r[3], r[4], r[2]) for r in sorted(hits, key=lambda r: r[3], reverse=True)][:limit]


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(draft_store, "enabled", lambda: True)
    monkeypatch.setattr(draft_store, "fetch", t.fetch)
    monkeypatch.setattr(draft_store, "store", t.store)
    monkeypatch.setattr(draft_store, "history", t.history)
    return t


@pytest.fixture
def broken(monkeypatch):
    t = FakeTable(fail=True)
    monkeypatch.setattr(draft_store, "enabled", lambda: True)
    monkeypatch.setattr(draft_store, "fetch", t.fetch)
    monkeypatch.setattr(draft_store, "store", t.store)
    monkeypatch.setattr(draft_store, "history", t.history)
    return t


ISSUE, KIND = "2026-09-25", "pm_friday"


def _touch(path, body, when):
    path.write_text(body, encoding="utf-8")
    os.utime(path, (when.timestamp(), when.timestamp()))


# ── append-only ──────────────────────────────────────────────────────────────

def test_a_later_save_does_not_destroy_the_earlier_one(table):
    table.store(ISSUE, KIND, "## Key Headlines\n- the good version\n")
    table.store(ISSUE, KIND, "")            # an empty box must not wipe it
    table.store(ISSUE, KIND, "## Key Headlines\n- oops\n")
    bodies = [row[2] for row in table.history(ISSUE, KIND)]
    assert "## Key Headlines\n- the good version\n" in bodies
    assert table.fetch(ISSUE, KIND)[0] == "## Key Headlines\n- oops\n"


def test_an_unchanged_body_is_not_appended_again(table):
    for _ in range(5):
        table.store(ISSUE, KIND, "## Comments\n- same\n")
    assert len(table.history(ISSUE, KIND)) == 1


def test_an_empty_body_is_never_stored(table):
    assert table.store(ISSUE, KIND, "   \n  ") == ""
    assert table.history(ISSUE, KIND) == []


# ── restore: newest wins, both directions ────────────────────────────────────

def test_restore_brings_the_draft_back_when_the_container_is_fresh(table, tmp_path):
    """The reboot case: Snowflake has the draft, the new container has nothing."""
    table.store(ISSUE, KIND, "## Technicals\n- written before the reboot\n")
    p = tmp_path / "commentary_pm_friday_2026-09-25.md"
    assert not p.exists()

    msg = draft_store.restore(p, ISSUE, KIND)

    assert p.read_text(encoding="utf-8") == "## Technicals\n- written before the reboot\n"
    assert "restored" in msg.lower()


def test_restore_pushes_up_a_local_file_snowflake_has_never_seen(table, tmp_path):
    p = tmp_path / "d.md"
    _touch(p, "## Comments\n- typed on the desktop\n", datetime.now(timezone.utc))

    draft_store.restore(p, ISSUE, KIND)

    assert table.fetch(ISSUE, KIND)[0] == "## Comments\n- typed on the desktop\n"


def test_a_newer_hand_edit_is_not_overwritten_by_the_database(table, tmp_path):
    """commentary.py promises the CLI can edit the file directly. A rule of
    'Snowflake always wins' would throw that edit away without a word."""
    table.store(ISSUE, KIND, "## Comments\n- the old database copy\n")
    remote_at = table.fetch(ISSUE, KIND)[1]

    p = tmp_path / "d.md"
    _touch(p, "## Comments\n- edited by hand just now\n", remote_at + timedelta(hours=1))

    draft_store.restore(p, ISSUE, KIND)

    assert p.read_text(encoding="utf-8") == "## Comments\n- edited by hand just now\n"
    assert table.fetch(ISSUE, KIND)[0] == "## Comments\n- edited by hand just now\n"


def test_a_newer_database_copy_wins_over_a_stale_file(table, tmp_path):
    p = tmp_path / "d.md"
    _touch(p, "## Comments\n- yesterday's local file\n",
           datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc))
    table.store(ISSUE, KIND, "## Comments\n- typed on the deployed page today\n")

    draft_store.restore(p, ISSUE, KIND)

    assert p.read_text(encoding="utf-8") == "## Comments\n- typed on the deployed page today\n"


def test_identical_copies_are_left_alone(table, tmp_path):
    body = "## Comments\n- same both sides\n"
    table.store(ISSUE, KIND, body)
    p = tmp_path / "d.md"
    _touch(p, body, datetime.now(timezone.utc))

    assert draft_store.restore(p, ISSUE, KIND) == ""
    assert len(table.history(ISSUE, KIND)) == 1


# ── an outage must not stop the letter ───────────────────────────────────────

def test_restore_is_silent_and_harmless_when_snowflake_is_down(broken, tmp_path):
    p = tmp_path / "d.md"
    _touch(p, "## Comments\n- still writable\n", datetime.now(timezone.utc))

    msg = draft_store.restore(p, ISSUE, KIND)

    assert p.read_text(encoding="utf-8") == "## Comments\n- still writable\n"
    assert "could not" in msg.lower()


def test_backup_reports_rather_than_raises_when_snowflake_is_down(broken, tmp_path):
    p = tmp_path / "d.md"
    p.write_text("## Comments\n- x\n", encoding="utf-8")
    assert "could not" in draft_store.backup(p, ISSUE, KIND).lower()


def test_backup_on_a_missing_file_reports_rather_than_raises(table, tmp_path):
    assert "could not read" in draft_store.backup(tmp_path / "nope.md", ISSUE, KIND).lower()


def test_everything_is_a_no_op_when_snowflake_is_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(draft_store, "enabled", lambda: False)
    p = tmp_path / "d.md"
    p.write_text("## Comments\n- local only\n", encoding="utf-8")

    assert draft_store.restore(p, ISSUE, KIND) == ""
    assert draft_store.history(ISSUE, KIND) == []
    assert "not configured" in draft_store.store(ISSUE, KIND, "x").lower()
    # And the file is untouched, because local-only has to keep working.
    assert p.read_text(encoding="utf-8") == "## Comments\n- local only\n"


# ── the collision trap ───────────────────────────────────────────────────────

def test_it_never_reads_snowflake_schema():
    """CLAUDE.md: five modules default SNOWFLAKE_SCHEMA to their own schema, so
    setting it for one empties the others. This module names its table in full
    and must take no part in that."""
    src = open(os.path.join(_HERE, "..", "letter", "draft_store.py"), encoding="utf-8").read()
    body = src.split('"""', 2)[2]          # past the module docstring
    assert "SNOWFLAKE_SCHEMA" not in body
    assert draft_store.TABLE == "JSA.LETTER.DRAFTS"


def test_it_does_not_import_snowflake_db_by_bare_name():
    """A bare `import snowflake_db` gets whichever of the six copies a page
    loaded first. The private-name loader is the point.

    Checked by AST rather than by searching the text, because the docstring
    discusses the very statement it must not contain."""
    import ast
    src = open(os.path.join(_HERE, "..", "letter", "draft_store.py"), encoding="utf-8").read()
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imported.add(node.module.split(".")[0])
    assert "snowflake_db" not in imported
    assert "_letter_draft_db" in src


# ── the prior-Friday settles ────────────────────────────────────────────────
# Added 2026-09-26. The same table now carries the six settles typed off last
# week's letter, under KIND = "weekbase". They had exactly the commentary's
# problem -- hand-entered, only in out/, gone on the next reboot -- and none of
# the tests above would have caught it, because every one of them is about a
# markdown draft and the settles are a JSON file keyed by a different date.

from letter import build as letter_build  # noqa: E402
from letter import config as letter_config  # noqa: E402

FRIDAY = date(2026, 9, 18)
SETTLES = {"LEV6": 232.55, "GFV6": 355.075, "LEZ6": 230.10}


def test_the_kind_does_not_collide_with_a_commentary_slug():
    """
    One namespace. If a format were ever named "weekbase" the two would share
    a row and each would look like a corrupt version of the other.
    """
    slugs = set(letter_config.FORMAT_FOR_DAY.values()) | {"am"}
    assert draft_store.WEEK_BASE_KIND not in slugs


def test_the_settles_come_back_on_a_fresh_container(table, tmp_path):
    """The reboot. out/ is empty and the week's numbers are still typed."""
    letter_build.save_week_base(tmp_path / "wb.json", SETTLES)
    draft_store.backup(tmp_path / "wb.json", FRIDAY, draft_store.WEEK_BASE_KIND)

    fresh = tmp_path / "fresh" / "weekbase_2026-09-18.json"
    msg = draft_store.restore(fresh, FRIDAY, draft_store.WEEK_BASE_KIND,
                              label="Prior-Friday settles")

    assert letter_build.load_week_base(fresh) == SETTLES
    assert "restored" in msg.lower()


def test_the_restore_line_does_not_call_them_a_draft(table, tmp_path):
    """
    "Draft restored" over the settles sends someone looking for writing that
    never moved. The label is the whole reason restore() takes one.
    """
    letter_build.save_week_base(tmp_path / "wb.json", SETTLES)
    draft_store.backup(tmp_path / "wb.json", FRIDAY, draft_store.WEEK_BASE_KIND)

    msg = draft_store.restore(tmp_path / "gone.json", FRIDAY,
                              draft_store.WEEK_BASE_KIND,
                              label="Prior-Friday settles")

    assert msg.startswith("Prior-Friday settles restored")
    assert "draft" not in msg.lower()


def test_monday_and_thursday_share_one_row(table, tmp_path):
    """
    Keyed by the FRIDAY, like the filename. Keying by the letter's own date
    would make every day of the week its own row and the six numbers would be
    typed again on each one -- which is the thing week_base_path already fixed
    on disk, and would have been reintroduced in Snowflake.
    """
    monday, thursday = date(2026, 9, 21), date(2026, 9, 24)
    assert letter_build.prior_friday_of(monday) == letter_build.prior_friday_of(thursday)

    letter_build.save_week_base(tmp_path / "mon.json", SETTLES)
    draft_store.backup(tmp_path / "mon.json",
                       letter_build.prior_friday_of(monday),
                       draft_store.WEEK_BASE_KIND)

    thu = tmp_path / "thu.json"
    draft_store.restore(thu, letter_build.prior_friday_of(thursday),
                        draft_store.WEEK_BASE_KIND)
    assert letter_build.load_week_base(thu) == SETTLES


def test_a_corrected_settle_does_not_destroy_the_one_it_replaced(table, tmp_path):
    """
    2026-09-25: a wrong October was saved and there was no way back to what it
    replaced. Append-only means the earlier set is still there.
    """
    p = tmp_path / "wb.json"
    letter_build.save_week_base(p, {"GFV6": 999.000})
    draft_store.backup(p, FRIDAY, draft_store.WEEK_BASE_KIND)
    letter_build.save_week_base(p, {"GFV6": 355.075})
    draft_store.backup(p, FRIDAY, draft_store.WEEK_BASE_KIND)

    versions = table.history(FRIDAY, draft_store.WEEK_BASE_KIND)
    assert len(versions) == 2
    assert "999.0" in versions[1][2]
    assert letter_build.load_week_base(p) == {"GFV6": 355.075}


def test_the_same_settles_in_a_different_order_are_not_a_new_version(table, tmp_path):
    """
    The body is compared as TEXT, so dict order alone would append a row that
    differs only in line order -- and a history of those is a history of
    nothing. save_week_base sorts its keys for exactly this.
    """
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    letter_build.save_week_base(a, SETTLES)
    letter_build.save_week_base(b, dict(reversed(list(SETTLES.items()))))
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")

    draft_store.backup(a, FRIDAY, draft_store.WEEK_BASE_KIND)
    draft_store.backup(b, FRIDAY, draft_store.WEEK_BASE_KIND)
    assert len(table.history(FRIDAY, draft_store.WEEK_BASE_KIND)) == 1


def test_a_restored_file_cannot_overwrite_a_real_settle(table, tmp_path):
    """
    Why the restore can run unconditionally rather than only when a base is
    missing. apply_week_base fills a contract with NO base; a contract that got
    one from the futures history keeps it, so a stale typed number from
    Snowflake can never displace real data.
    """
    ctx = {"live_cattle": [{"ticker": "LEV6", "week_base_missing": False,
                            "change_week": -1.25, "settle": 231.30}],
           "feeder_cattle": [{"ticker": "GFV6", "week_base_missing": True,
                              "settle": 356.00}]}
    filled = letter_build.apply_week_base(ctx, {"LEV6": 999.000, "GFV6": 355.075})

    assert ctx["live_cattle"][0]["change_week"] == -1.25      # the real bar stands
    assert ctx["feeder_cattle"][0]["change_week"] == 0.925    # 356.00 - 355.075
    assert len(filled) == 1                                  # only the missing one
    assert ctx["live_cattle"][0].get("week_base_source") is None


def test_the_settles_still_save_locally_when_snowflake_is_down(broken, tmp_path):
    p = tmp_path / "wb.json"
    letter_build.save_week_base(p, SETTLES)
    assert "could not" in draft_store.backup(p, FRIDAY, draft_store.WEEK_BASE_KIND).lower()
    assert letter_build.load_week_base(p) == SETTLES
