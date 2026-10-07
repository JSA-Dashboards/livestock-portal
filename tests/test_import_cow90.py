"""Proof that the Frozen 90s import mirror cannot quietly destroy its own series.

The table it writes is the ONLY copy of that history — NW_LS421 is behind an
IP block the portal cannot reach, so a bad rewrite is not recoverable from the
page. Everything pinned here is a way that could happen silently.

    python -m pytest tests/test_import_cow90.py -q
"""

import ast
import os
import sys
from datetime import date

import pandas as pd
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "apps", "beef_trimmings"))
sys.path.insert(0, os.path.join(_HERE, "..", "scripts"))

import import_cow90 as ic  # noqa: E402

CRON = os.path.join(_HERE, "..", "scripts", "bank_import_cow90.py")


def _frame(n_weeks=5):
    rows = []
    for i in range(n_weeks):
        for origin in ("Australia/NZ", "South America"):
            rows.append({"report_date": pd.Timestamp(2026, 9, 4) + pd.Timedelta(days=7 * i),
                         "origin": origin, "avg_price": 340.0, "low": 338.0,
                         "high": 342.0, "n": 2})
    return pd.DataFrame(rows)


class _Cur:
    """Records SQL and answers COUNT(*) with whatever the test set."""

    def __init__(self, existing_rows=0, table_present=True, fail_on=None):
        self.existing = existing_rows
        self.present = table_present
        self.fail_on = fail_on
        self.sql = []
        self.executed_many = 0
        self._last = None

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError(f"denied: {self.fail_on}")
        if "INFORMATION_SCHEMA.TABLES" in sql:
            self._last = (1 if self.present else 0,)
        elif "COUNT(*)" in sql:
            self._last = (self.existing,)
        return self

    def executemany(self, sql, rows):
        self.sql.append(" ".join(sql.split()))
        # The INSERT goes through HERE, not execute(). A fail_on that only
        # fired in execute() left the rollback path untested while the test
        # still passed on the happy path.
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError(f"denied: {self.fail_on}")
        self.executed_many = len(rows)

    def fetchone(self):
        return self._last

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


# ── the guard that makes a rewrite safe ─────────────────────────────────────

def test_a_shrunken_series_is_refused():
    """MARS flaps and can answer 200 with a partial payload.

    Measured 2026-10-07: bare GETs to marsapi returned 503 repeatedly while a
    retrying session got 200. A short payload rewritten over seven years of
    history destroys data the page has no other copy of.
    """
    cur = _Cur(existing_rows=260)
    n, err = ic.bank(_Conn(cur), _frame(5))       # 10 rows against 260 held
    assert n == 0 and "shrink" in err.lower()
    assert not any("DELETE" in s for s in cur.sql), "it must not delete before refusing"


def test_force_overrides_the_shrink_guard():
    cur = _Cur(existing_rows=260)
    n, err = ic.bank(_Conn(cur), _frame(5), force=True)
    assert err == "" and n == 10
    assert any("DELETE" in s for s in cur.sql)


def test_a_series_that_grew_is_written():
    cur = _Cur(existing_rows=260)
    n, err = ic.bank(_Conn(cur), _frame(140))     # 280 rows
    assert err == "" and n == 280


def test_an_empty_frame_never_reaches_the_delete():
    """The failure that would wipe the table and report success."""
    cur = _Cur(existing_rows=260)
    n, err = ic.bank(_Conn(cur), pd.DataFrame(columns=ic.COLUMNS))
    assert n == 0 and err
    assert not any("DELETE" in s for s in cur.sql)
    n, err = ic.bank(_Conn(cur), None)
    assert n == 0 and err


def test_the_rewrite_is_one_transaction():
    """A failure between DELETE and INSERT would leave the page with nothing."""
    cur = _Cur(existing_rows=10)
    ic.bank(_Conn(cur), _frame(140))
    joined = " | ".join(cur.sql)
    assert joined.index("BEGIN") < joined.index("DELETE") < joined.index("COMMIT")


def test_a_failed_write_rolls_back():
    cur = _Cur(existing_rows=10, fail_on="INSERT")
    n, err = ic.bank(_Conn(cur), _frame(140))
    assert n == 0 and "Could not write" in err
    assert any("ROLLBACK" in s for s in cur.sql)


# ── the permission trap ─────────────────────────────────────────────────────

def test_ensure_table_looks_before_it_creates():
    """CREATE TABLE IF NOT EXISTS still needs CREATE TABLE on the schema.

    This table lives in JSA.BEEF_TRIMMINGS where the ingest identity has DML
    and no DDL, so the no-op failed the whole run with a permission error that
    reads like a missing table and is neither.
    """
    cur = _Cur(table_present=True)
    assert ic.ensure_table(_Conn(cur)) == ""
    assert not any("CREATE TABLE" in s for s in cur.sql), \
        "it issued DDL for a table that already exists"


def test_ensure_table_still_creates_a_genuinely_absent_table():
    cur = _Cur(table_present=False)
    assert ic.ensure_table(_Conn(cur)) == ""
    assert any("CREATE TABLE" in s for s in cur.sql)


# ── one implementation, not two ─────────────────────────────────────────────

def test_the_cron_defines_no_fetcher_of_its_own():
    """It imports the page's fetcher; a second copy running unattended is the
    snowflake_db-times-five problem with no renderer to catch the drift."""
    tree = ast.parse(open(CRON, encoding="utf-8").read())
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for banned in ("fetch_live", "bank", "ensure_table", "_session"):
        assert banned not in defined, f"bank_import_cow90.py redefines {banned}"
    src = open(CRON, encoding="utf-8").read()
    assert "reportSection" not in src and "country_of_origin" not in src


def test_the_page_delegates_to_the_module():
    app = os.path.join(_HERE, "..", "apps", "beef_trimmings", "app.py")
    src = open(app, encoding="utf-8").read()
    assert "import import_cow90" in src
    assert "import_cow90.fetch_live(" in src
    assert "country_of_origin" not in src, \
        "app.py parses NW_LS421 again instead of using the shared module"


def test_the_retrying_session_is_used_because_mars_flaps():
    """A bare requests.get reports an outage that is not happening."""
    src = open(os.path.join(_HERE, "..", "apps", "beef_trimmings",
                            "import_cow90.py"), encoding="utf-8").read()
    assert "status_forcelist" in src and "503" in src
    assert "_session()" in src


def test_the_upper_bound_reaches_past_today():
    """A bound of exactly today drops a report published for the current week."""
    src = open(os.path.join(_HERE, "..", "apps", "beef_trimmings",
                            "import_cow90.py"), encoding="utf-8").read()
    assert "timedelta(days=2)" in src
