"""
Guards for the Cattle Cycles refresh job and the page's Snowflake read path.

THE FIRST GROUP IS THE ONE THAT MATTERS MOST, and it is the same trap
tests/test_cattle_cycles.py pins on the page side, re-pinned here because the
FETCHER is where it would actually be reintroduced. NASS carries both

    CATTLE, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT
    CATTLE, STEERS & HEIFERS, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT

and the first is a strict substring of the second. A fetcher matching with
`in` rather than `==` merges two price definitions into one plausible series:
they overlap on 884 months and differ on all 884, and the merge moved the
headline median cycle from 7.4 years to 10.1 while rendering perfectly.

NOTHING HERE TOUCHES THE NETWORK. The parsing tests feed the real dump's line
format through `_qualifies`/`_num`/`_period`, and the write tests run against
a recording fake cursor. A test that needed marsapi or a 464MB download would
not be run, and a guard nobody runs is worse than none.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "cattle_cycles"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(ROOT))

import cycles  # noqa: E402


def _load_job():
    """deploy/refresh_cattle_cycles.py by path -- `deploy` is not a package."""
    path = ROOT / "deploy" / "refresh_cattle_cycles.py"
    spec = importlib.util.spec_from_file_location("_cyc_refresh_job", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cyc_refresh_job"] = mod
    spec.loader.exec_module(mod)
    return mod


job = _load_job()


@pytest.fixture(scope="module")
def seed():
    s = cycles.load()
    assert s, "the committed seed must load"
    return s


def _row(short_desc, year, month, value, agg="NATIONAL", freq="MONTHLY",
         commodity="CATTLE"):
    """One bulk-dump line, laid out at the real 1-indexed column numbers."""
    f = [""] * 39
    f[job.COL_COMMODITY - 1] = commodity
    f[job.COL_SHORT_DESC - 1] = short_desc
    f[job.COL_AGG - 1] = agg
    f[job.COL_YEAR - 1] = str(year)
    f[job.COL_FREQ - 1] = freq
    f[job.COL_BEGIN - 1] = f"{month:02d}"
    f[job.COL_VALUE - 1] = str(value)
    return f


# -- the exact-short_desc rule ------------------------------------------------

GE500 = "CATTLE, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT"


def test_the_substring_trap_is_still_live():
    """If these ever stop colliding the trap is gone -- but so is the reason
    every test below it exists, so check before deleting any of them."""
    near = job.COLLIDING_SHORT_DESC
    assert GE500 in job.SERIES
    assert near not in job.SERIES
    assert "GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT" in near
    assert GE500 != near


def test_the_colliding_series_is_rejected_by_the_fetcher():
    """The whole point: an exact match keeps it out, a substring match lets it in."""
    assert job._qualifies(_row(GE500, 1953, 1, 19.1)) == "cattle_ge500"
    assert job._qualifies(_row(job.COLLIDING_SHORT_DESC, 1953, 1, 21.9)) is None


def test_the_selection_compares_with_equality_not_membership():
    """Pinned by AST as well as by behaviour. The behavioural test above passes
    for a dict lookup and fails for `in`; this one fails for any `in`/startswith
    comparison against a short_desc field reintroduced anywhere in the module,
    including in a helper the behavioural test does not route through."""
    tree = ast.parse((ROOT / "deploy" / "refresh_cattle_cycles.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_qualifies")
    for node in ast.walk(fn):
        assert not isinstance(node, ast.Compare) or not any(
            isinstance(o, (ast.In, ast.NotIn)) for o in node.ops), (
            "_qualifies must select by exact short_desc, never by membership")
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("startswith", "endswith", "find"), node.attr


def test_only_national_monthly_rows_qualify():
    """A state or an annual row has the same short_desc and a different number."""
    assert job._qualifies(_row(GE500, 2026, 8, 1.0, agg="STATE")) is None
    assert job._qualifies(_row(GE500, 2026, 8, 1.0, freq="ANNUAL")) is None
    assert job._qualifies(_row(GE500, 2026, 8, 1.0)) == "cattle_ge500"


# -- the in-band missing markers ----------------------------------------------

@pytest.mark.parametrize("raw", ["-", "(D)", "(NA)", "(Z)", "(S)", "", "   "])
def test_an_absent_value_is_none_rather_than_an_exception(raw):
    """Both feeds mark an absent figure IN BAND. BLS writes a bare "-" for
    October 2025 -- the one hole in 113 years of CPI -- and NASS writes (D) for
    withheld. Read naively each raises mid-stream, which on a 10-million-line
    scan reads as a corrupt download rather than a documented gap."""
    assert job._num(raw) is None


def test_a_thousands_separator_survives():
    assert job._num("1,234.5") == 1234.5
    assert job._num("125") == 125.0


def test_m13_is_not_a_month():
    """BLS writes the ANNUAL AVERAGE as period M13 in the same column as
    M01..M12, 113 times in that file. Admitting it adds a thirteenth
    observation a year near the year's mean, which charts perfectly."""
    assert job._period("2025", "13") is None
    assert job._period("2025", "00") is None
    assert job._period("2025", "12") == "2025-12"


# -- the seed payload ---------------------------------------------------------

def test_describe_reports_a_hole_rather_than_just_a_count(seed):
    """The CPI series is 1,364 months over a 1,365-month span: 2025-10 is
    absent, and `n` alone cannot say that."""
    d = job.describe(seed["cpi_u"]["rows"])
    assert d["first"] == "1913-01" and d["last"] == "2026-09"
    assert d["n"] == 1364 and d["missing"] == ["2025-10"]


def test_a_contiguous_series_reports_no_hole(seed):
    d = job.describe(seed["series"]["cows"]["rows"])
    assert d["missing"] == [] and d["n"] == 884


def test_seed_payload_round_trips_the_committed_file(seed):
    """The job and whatever built the seed must agree completely. If this ever
    fails, --write-json would rewrite the committed file into a different
    shape, and the page reads that file whenever Snowflake is unreachable."""
    prices = {k: seed["series"][k]["rows"] for k in cycles.SERIES}
    built = job.seed_payload(prices, seed["cpi_u"]["rows"], seed)
    on_disk = json.loads(cycles.DATA.read_text(encoding="utf-8"))
    assert json.dumps(built, sort_keys=True) == json.dumps(on_disk, sort_keys=True)


# -- idempotency of the write -------------------------------------------------

def test_an_unchanged_period_is_not_written(seed):
    """The whole reason the schedule can be blunt: the catch-up run fetches
    both feeds and writes nothing."""
    prices = {k: seed["series"][k]["rows"] for k in cycles.SERIES}
    cpi = seed["cpi_u"]["rows"]
    first = job.pending(prices, cpi, {})
    assert len(first) == sum(len(v) for v in prices.values()) + len(cpi)
    have = {(r[0], r[1]): r[2] for r in first}
    assert job.pending(prices, cpi, have) == []


def test_a_revised_period_IS_written(seed):
    """NASS restates price received, so an existing period changing is normal
    and is exactly what must be written -- append-only keeps the superseded
    figure rather than burying it."""
    prices = {k: dict(seed["series"][k]["rows"]) for k in cycles.SERIES}
    cpi = dict(seed["cpi_u"]["rows"])
    have = {(k, p): v for k, rows in prices.items() for p, v in rows.items()}
    have.update({(job.CPI_KEY, p): v for p, v in cpi.items()})
    assert job.pending(prices, cpi, have) == []
    prices["cows"]["2026-08"] = prices["cows"]["2026-08"] + 0.4
    out = job.pending(prices, cpi, have)
    assert [(r[0], r[1]) for r in out] == [("cows", "2026-08")]


def test_a_new_month_is_written(seed):
    prices = {k: dict(seed["series"][k]["rows"]) for k in cycles.SERIES}
    cpi = dict(seed["cpi_u"]["rows"])
    have = {(k, p): v for k, rows in prices.items() for p, v in rows.items()}
    have.update({(job.CPI_KEY, p): v for p, v in cpi.items()})
    prices["calves"]["2026-09"] = 420.0
    cpi["2026-10"] = 337.5
    out = {(r[0], r[1]) for r in job.pending(prices, cpi, have)}
    assert out == {("calves", "2026-09"), (job.CPI_KEY, "2026-10")}


def test_every_written_row_carries_its_own_provenance(seed):
    """SHORT_DESC on the row is what makes the substring trap visible IN THE
    DATA rather than only in this file: two definitions merged upstream would
    show up as one series key carrying two short_descs."""
    prices = {k: seed["series"][k]["rows"] for k in cycles.SERIES}
    rows = job.pending(prices, seed["cpi_u"]["rows"], {})
    by_key = {}
    for series, _period, _v, short_desc, source in rows:
        by_key.setdefault(series, set()).add((short_desc, source))
    for key in cycles.SERIES:
        assert len(by_key[key]) == 1, by_key[key]
        (desc, source), = by_key[key]
        assert source == "nass" and job.SERIES[desc] == key
    assert by_key[job.CPI_KEY] == {(job.CPI_SERIES_ID, "bls")}


# -- the write itself ---------------------------------------------------------

class _Cur:
    def __init__(self, log, rows=None):
        self.log, self._rows = log, rows or []

    def execute(self, sql, params=None):
        # NOT truncated: the read's QUALIFY clause is the thing under test and
        # it sits past any reasonable cut.
        self.log.append(("execute", " ".join(sql.split()), params))
        return self

    def executemany(self, sql, seq):
        self.log.append(("executemany", " ".join(sql.split())[:60], len(seq)))
        return self

    def fetchall(self):
        return self._rows


class _Conn:
    """Records statements. `fail_create_schema` reproduces CME_INGEST_ROLE,
    which does not hold CREATE SCHEMA on JSA."""
    def __init__(self, rows=None, fail_create_schema=False):
        self.log, self._rows = [], rows or []
        self.fail_create_schema = fail_create_schema
        self.commits = 0

    def cursor(self):
        return _Cur(self.log, self._rows)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


class _SchemaDenyingConn(_Conn):
    def cursor(self):
        outer = self

        class C(_Cur):
            def execute(self, sql, params=None):
                if "CREATE SCHEMA" in sql:
                    outer.log.append(("execute", "CREATE SCHEMA denied", None))
                    raise RuntimeError("Insufficient privileges to operate on "
                                       "database 'JSA'")
                return super().execute(sql, params)

        return C(self.log, self._rows)


def test_create_schema_failure_does_not_stop_the_job():
    """CME_INGEST_ROLE lacks CREATE SCHEMA on JSA and the schema already
    exists, so raising there would stop a job whose schema is sitting in front
    of it. If it really is missing, the CREATE TABLE says so instead."""
    conn = _SchemaDenyingConn()
    n = job.write(conn, [("cows", "2026-08", 1.0, "d", "nass")])
    assert n == 1
    assert any("CREATE TABLE" in s for _k, s, *_ in conn.log)
    assert conn.commits == 1


def test_writing_nothing_still_creates_the_table_and_does_not_commit():
    conn = _Conn()
    assert job.write(conn, []) == 0
    assert any("CREATE TABLE" in s for _k, s, *_ in conn.log)
    assert not any(k == "executemany" for k, *_ in conn.log)
    assert conn.commits == 0


def test_a_large_first_write_is_chunked_rather_than_row_at_a_time():
    """The first run writes about 5,058 rows; a round trip each makes that
    minutes instead of seconds."""
    rows = [("cows", f"20{i:02d}-01", float(i), "d", "nass") for i in range(99)]
    conn = _Conn()
    assert job.write(conn, rows * 30) == 2970
    sends = [n for k, _s, n in conn.log if k == "executemany"]
    assert sends and max(sends) <= 1000 and sum(sends) == 2970


def test_the_read_is_newest_wins_per_series_and_period():
    conn = _Conn(rows=[("cows", "2026-08", 1.0)])
    job.existing(conn)
    sql = next(s for k, s, *_ in conn.log if k == "execute")
    assert "QUALIFY ROW_NUMBER()" in sql
    assert "PARTITION BY SERIES, PERIOD" in sql
    assert "ORDER BY RECORDED_AT DESC" in sql


# -- the shortfall guard ------------------------------------------------------

def test_a_truncated_fetch_is_a_failure_rather_than_a_quiet_month(seed):
    """A cleanly-truncated stream yields a SHORT series, and because unchanged
    periods are skipped the job would otherwise write nothing and exit 0 --
    indistinguishable from a month in which nothing moved."""
    prices = {k: dict(seed["series"][k]["rows"]) for k in cycles.SERIES}
    cpi = dict(seed["cpi_u"]["rows"])
    assert job._shortfall(prices, cpi, seed) == []
    prices["calves"].pop("1970-01")
    assert any("calves" in s for s in job._shortfall(prices, cpi, seed))
    prices["calves"]["1970-01"] = 1.0
    cpi.pop("1970-01")
    assert any(job.CPI_KEY in s for s in job._shortfall(prices, cpi, seed))


def test_a_longer_fetch_is_not_a_shortfall(seed):
    """The table is supposed to run AHEAD of the committed seed."""
    prices = {k: dict(seed["series"][k]["rows"]) for k in cycles.SERIES}
    cpi = dict(seed["cpi_u"]["rows"])
    prices["cows"]["2026-09"] = 1.0
    cpi["2026-10"] = 1.0
    assert job._shortfall(prices, cpi, seed) == []


# -- the job's own hygiene ----------------------------------------------------

def test_the_job_names_its_table_in_full_and_never_reads_SNOWFLAKE_SCHEMA():
    """CLAUDE.md: setting SNOWFLAKE_SCHEMA overrides all nine modules that each
    default it to the schema they own, and breaks the other eight silently."""
    src = (ROOT / "deploy" / "refresh_cattle_cycles.py").read_text(encoding="utf-8")
    assert "SNOWFLAKE_SCHEMA" not in src
    assert job.TABLE == "JSA.CME_FEEDER_CATTLE.CATTLE_CYCLE_PRICES"
    assert job.TABLE.count(".") == 2


def test_the_job_loads_snowflake_db_by_path_under_a_private_name():
    """`snowflake_db` exists five times and is imported by bare name by several
    pages, so whichever loads first wins for every other."""
    src = (ROOT / "deploy" / "refresh_cattle_cycles.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name == "snowflake_db" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "snowflake_db"
    assert "spec_from_file_location(\"_cyc_snowflake_db\"" in src


# -- the page's read path -----------------------------------------------------

class _PageCur:
    def __init__(self, rows, boom=False):
        self._rows, self._boom = rows, boom

    def execute(self, sql, params=None):
        if self._boom:
            raise RuntimeError("Snowflake is unreachable")
        return self

    def fetchall(self):
        return self._rows


class _PageConn:
    def __init__(self, rows=None, boom=False):
        self._rows, self._boom = rows or [], boom

    def cursor(self):
        return _PageCur(self._rows, self._boom)


def _table_rows(seed, extra=None):
    rows = [(k, p, v) for k in cycles.SERIES
            for p, v in seed["series"][k]["rows"].items()]
    rows += [(cycles.CPI_KEY, p, v) for p, v in seed["cpi_u"]["rows"].items()]
    return rows + list(extra or [])


def test_the_fallback_renders_when_snowflake_is_empty(seed):
    """The job may never have run. The page must still draw the whole record."""
    d = cycles.load(_PageConn(rows=[]))
    assert d and d["source"] == "file"
    assert len(d["series"]["cattle_ge500"]["rows"]) == 1405
    assert cycles.summary(d)["context"]["kind"] == "bull"


def test_the_fallback_renders_when_snowflake_raises(seed):
    d = cycles.load(_PageConn(boom=True))
    assert d and d["source"] == "file"
    assert cycles.summary(d)["trough_to_trough"]


def test_no_connection_at_all_reads_the_committed_seed(seed):
    assert cycles.load(None)["source"] == "file"
    assert cycles.load()["source"] == "file"


def test_a_complete_table_is_preferred_over_the_file(seed):
    d = cycles.load(_PageConn(rows=_table_rows(seed)))
    assert d["source"] == "snowflake"
    assert len(d["series"]["cows"]["rows"]) == 884
    # And it must produce the same answer as the file, since the rows are the
    # same numbers -- a read path that quietly reshaped them would show up here.
    assert (cycles.summary(d)["trough_to_trough"]
            == cycles.summary(cycles.load())["trough_to_trough"])


def test_the_table_advances_the_page(seed):
    """The point of the job: a month the committed seed does not have."""
    rows = _table_rows(seed, extra=[("cows", "2026-09", 150.0),
                                    ("calves", "2026-09", 430.0),
                                    ("cattle_ge500", "2026-09", 250.0),
                                    (cycles.CPI_KEY, "2026-10", 337.5)])
    d = cycles.load(_PageConn(rows=rows))
    assert d["source"] == "snowflake"
    assert d["series"]["cows"]["rows"]["2026-09"] == 150.0
    assert cycles.summary(d)["last"].strftime("%Y-%m") == "2026-09"


def test_a_short_table_falls_back_WHOLE_rather_than_splicing(seed):
    """ALL OR NOTHING. Taking whichever source is longer per series would mean
    deflating a table price series by a file CPI -- and every cycle date here
    is a product of the price series and the deflator together, so a mixed read
    is a splice. A splice renders perfectly and moves the headline, which is
    the failure this page's module note opens with."""
    rows = [r for r in _table_rows(seed) if not (r[0] == "cows" and r[1] == "1960-01")]
    d = cycles.load(_PageConn(rows=rows))
    assert d["source"] == "file"
    assert len(d["series"]["cows"]["rows"]) == 884


def test_a_table_missing_cpi_entirely_falls_back(seed):
    """Without a deflator the page would silently chart nominal prices under a
    caption saying real."""
    rows = [r for r in _table_rows(seed) if r[0] != cycles.CPI_KEY]
    assert cycles.load(_PageConn(rows=rows))["source"] == "file"


def test_a_table_missing_one_whole_series_falls_back(seed):
    rows = [r for r in _table_rows(seed) if r[0] != "cows"]
    assert cycles.load(_PageConn(rows=rows))["source"] == "file"


def test_the_source_reaches_the_summary_so_the_page_can_name_it(seed):
    """A failed refresh job is INVISIBLE on this chart -- the seed draws every
    figure perfectly. The caption is the only tell, so the marker has to
    survive the trip through summary()."""
    assert cycles.summary(cycles.load())["source"] == "file"
    assert cycles.summary(cycles.load(_PageConn(rows=_table_rows(seed))))["source"] \
        == "snowflake"


def test_the_page_names_the_source_in_a_caption():
    src = (APP_DIR / "app.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    assert "source_word" in src
    caps = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "caption"
            and any(isinstance(x, ast.Name) and x.id == "source_word"
                    for x in ast.walk(n))]
    assert caps, "no caption derives the source; a stale table would be invisible"
    # Defined once, ABOVE every use -- the script-order trap CLAUDE.md records
    # for the WASDE panel, which NameErrored on the live page while a
    # source-text test passed.
    assign = min(n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "source_word"
                         for t in n.targets))
    assert assign < min(c.lineno for c in caps)


def test_the_page_loads_snowflake_db_by_path_under_a_private_name():
    src = (APP_DIR / "app.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name == "snowflake_db" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "snowflake_db"
    assert 'spec_from_file_location("_cyc_page_db"' in src


def test_the_page_only_connects_when_snowflake_is_the_backend():
    """get_conn() hands back SQLite when USE_SNOWFLAKE is unset, which would
    mean opening another page's local database file to run a query that cannot
    succeed against it."""
    src = (APP_DIR / "app.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "load_summary")
    guards = [n for n in ast.walk(fn) if isinstance(n, ast.If)]
    assert any(any(isinstance(c, ast.Attribute) and c.attr == "use_snowflake"
                   for c in ast.walk(g.test)) for g in guards)
    assert any(isinstance(n, ast.Try) and n.finalbody for n in ast.walk(fn)), (
        "the connection must be closed in a finally, or a Snowflake hiccup "
        "leaks one per cache miss")
