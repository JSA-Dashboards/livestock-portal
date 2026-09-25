"""
Durable storage for the letter drafts — JSA.LETTER.DRAFTS in Snowflake.

WHY THIS EXISTS. A draft used to live in exactly one place: `out/`, on the
machine the page happened to be running on. `out/` is gitignored and a
Streamlit Cloud reboot rebuilds the container from a fresh clone, so every
reboot destroyed every unsent draft, and the page said nothing about it. On
2026-09-25 that lost a nearly finished Friday letter. Nothing in the app had
ever written a draft anywhere a reboot could not reach.

THE TABLE IS APPEND-ONLY. Every save INSERTs; the current draft is the newest
row for its (issue_date, kind). There is no UPDATE and no DELETE, so no save
can overwrite an earlier version and `history()` can always hand one back.
That is the actual insurance — durability alone would still have let a bad
paste destroy an hour's writing.

IT WRITES BOTH PLACES, EVERY TIME. Snowflake survives the reboot; the file
keeps `python -m letter.build` working when Snowflake is unreachable. Either
one alone has a failure mode the other covers, and a draft is not the place to
be clever about it.

NEWEST WINS ON READ, and that is deliberate rather than "Snowflake is the
source of truth". Hand-editing `out/commentary_<kind>_<date>.md` in an editor
and re-running the build is a supported workflow -- commentary.py's docstring
promises it -- and a rule of "the database always wins" would silently discard
those edits, which is the same class of quiet loss this module exists to stop.
So `restore()` compares the file's mtime against SAVED_AT and keeps whichever
is newer, in UTC on both sides.

A SNOWFLAKE OUTAGE MUST NEVER STOP THE LETTER GOING OUT. Every call here
returns a status string instead of raising, and every Snowflake failure leaves
the on-disk path working exactly as it did before this module existed.

IT NEVER READS SNOWFLAKE_SCHEMA. CLAUDE.md records that five bundled modules
each default that variable to the schema they own, so setting it for one
silently empties the other four. This module takes no part in that: every
statement names JSA.LETTER.DRAFTS in full, so the session's schema is
irrelevant to it.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APPS = REPO / "apps"

TABLE = "JSA.LETTER.DRAFTS"

# Schema, created 2026-09-25 and owned by SYSADMIN rather than living in
# JSA.CME_FEEDER_CATTLE, on purpose: ACCOUNTADMIN owns that schema and SYSADMIN
# was never granted MODIFY on its tables, so a table put there could never be
# altered without an admin. Owning the schema means a column can be added.
DDL = [
    "CREATE SCHEMA IF NOT EXISTS JSA.LETTER",
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
            ISSUE_DATE DATE          NOT NULL,
            KIND       VARCHAR(32)   NOT NULL,
            BODY       VARCHAR       NOT NULL,
            SAVED_AT   TIMESTAMP_NTZ NOT NULL,
            SAVED_BY   VARCHAR(128)
        )""",
]


def enabled() -> bool:
    """Snowflake is configured. Same flag the rest of the portal uses."""
    return os.getenv("USE_SNOWFLAKE", "").strip().lower() in ("1", "true", "yes", "on")


def _load_db():
    """
    apps/cme_feeder_cattle/snowflake_db.py, under a PRIVATE module name.

    Exactly the trick sources._load_fci_db() uses, for the same reason:
    snowflake_db.py exists six times across two repos and Python caches modules
    by NAME, so a plain `import snowflake_db` inside the Streamlit process gets
    whichever page imported first. "_letter_draft_db" can never join that
    collision. Reusing the file rather than copying its key-pair logic also
    means there is no seventh copy of that to drift.
    """
    path = APPS / "cme_feeder_cattle" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_letter_draft_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_letter_draft_db"] = mod
    spec.loader.exec_module(mod)
    return mod


_CONN = None


def _conn():
    """One connection, reused. A login costs a second or more, and autosave
    fires on every blur -- per-call connections made typing feel broken."""
    global _CONN
    if _CONN is None:
        _CONN = _load_db().get_conn()
    return _CONN


def _drop_conn():
    global _CONN
    try:
        if _CONN is not None:
            _CONN.close()
    except Exception:
        pass
    _CONN = None


def _run(fn):
    """Call fn(cursor), reconnecting once. A cached connection outlives the
    session token it was opened with, so the first call after a long idle is
    expected to fail and expected to succeed on the retry."""
    for attempt in (1, 2):
        try:
            cur = _conn().cursor()
            try:
                return fn(cur)
            finally:
                cur.close()
        except Exception:
            _drop_conn()
            if attempt == 2:
                raise
    return None


def _who(source: str) -> str:
    try:
        host = socket.gethostname()
    except Exception:
        host = "?"
    return f"{source}@{host}"[:128]


def _mtime_utc(path: Path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def ensure_table() -> str:
    """Create the schema and table if they are missing. Safe to call every run."""
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    try:
        def go(cur):
            for stmt in DDL:
                cur.execute(stmt)
            return ""
        _run(go)
        return ""
    except Exception as e:
        return f"Could not reach Snowflake: {e}"


def fetch(issue, kind: str):
    """(body, saved_at_utc) for the newest saved version, or (None, None)."""
    if not enabled():
        return None, None
    try:
        def go(cur):
            cur.execute(
                f"SELECT BODY, SAVED_AT FROM {TABLE} "
                "WHERE ISSUE_DATE = %s AND KIND = %s "
                "ORDER BY SAVED_AT DESC LIMIT 1",
                (str(issue), kind),
            )
            return cur.fetchone()
        row = _run(go)
    except Exception:
        return None, None
    if not row:
        return None, None
    saved_at = row[1]
    if saved_at is not None and saved_at.tzinfo is None:
        # The column is TIMESTAMP_NTZ and store() writes UTC into it, so the
        # naive value that comes back IS UTC. Saying so explicitly is what
        # makes the comparison in restore() mean anything.
        saved_at = saved_at.replace(tzinfo=timezone.utc)
    return row[0], saved_at


def history(issue, kind: str, limit: int = 25) -> list:
    """Every saved version, newest first, as [(saved_at_utc, saved_by, body)]."""
    if not enabled():
        return []
    try:
        def go(cur):
            cur.execute(
                f"SELECT SAVED_AT, SAVED_BY, BODY FROM {TABLE} "
                "WHERE ISSUE_DATE = %s AND KIND = %s "
                "ORDER BY SAVED_AT DESC LIMIT %s",
                (str(issue), kind, int(limit)),
            )
            return cur.fetchall() or []
        rows = _run(go)
    except Exception:
        return []
    out = []
    for saved_at, saved_by, body in rows:
        if saved_at is not None and saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=timezone.utc)
        out.append((saved_at, saved_by, body))
    return out


def store(issue, kind: str, body: str, source: str = "app") -> str:
    """
    Append this version. Returns "" on success, or a message on failure.

    An unchanged body is skipped rather than inserted: autosave fires on every
    blur, and a history of fifty identical rows is a history of nothing.
    """
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    if not (body or "").strip():
        return ""
    try:
        current, _ = fetch(issue, kind)
        if current is not None and current == body:
            return ""

        def go(cur):
            cur.execute(
                f"INSERT INTO {TABLE} (ISSUE_DATE, KIND, BODY, SAVED_AT, SAVED_BY) "
                "VALUES (%s, %s, %s, %s, %s)",
                (str(issue), kind, body,
                 datetime.now(timezone.utc).replace(tzinfo=None), _who(source)),
            )
            return ""
        _run(go)
        return ""
    except Exception as e:
        return f"Could not save to Snowflake: {e}"


def backup(path: Path, issue, kind: str, source: str = "app") -> str:
    """Push what is on disk up to Snowflake."""
    try:
        body = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return f"Could not read {Path(path).name}: {e}"
    return store(issue, kind, body, source)


def restore(path: Path, issue, kind: str) -> str:
    """
    Reconcile disk and Snowflake before the draft is read. Newest wins.

    Returns a short line for the page to show, or "" when there was nothing to
    do. The three outcomes it reports are the three a person would want to
    know about: the draft came back from Snowflake, the local file was newer
    and was pushed up, or Snowflake could not be reached at all.
    """
    path = Path(path)
    if not enabled():
        return ""

    remote_body, remote_at = fetch(issue, kind)
    local_at = _mtime_utc(path)

    if remote_body is None:
        if local_at is not None:
            err = backup(path, issue, kind)
            return err or ""
        return ""

    if local_at is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(remote_body, encoding="utf-8")
        return f"Draft restored from Snowflake (saved {remote_at:%b %d %H:%M} UTC)."

    try:
        local_body = path.read_text(encoding="utf-8")
    except OSError:
        local_body = None

    if local_body == remote_body:
        return ""

    if remote_at is not None and local_at is not None and remote_at > local_at:
        path.write_text(remote_body, encoding="utf-8")
        return f"Draft restored from Snowflake (saved {remote_at:%b %d %H:%M} UTC)."

    err = store(issue, kind, local_body or "", "app")
    return err or ""
