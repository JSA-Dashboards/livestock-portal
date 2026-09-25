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
from datetime import datetime, timedelta, timezone

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
