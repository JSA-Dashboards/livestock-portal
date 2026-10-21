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

THE SECOND GROUP IS THE SAME TRAP ON THE INVENTORY SIDE, where it is sharper
still. `CATTLE, INCL CALVES - INVENTORY` is a strict PREFIX of

    CATTLE, INCL CALVES - INVENTORY, MEASURED IN $
    CATTLE, INCL CALVES - INVENTORY, MEASURED IN $ / HEAD

and all three are NATIONAL / INVENTORY / FIRST OF JAN / TOTAL over the same
160 years, so nothing but the exact short_desc separates a head count from a
dollar value. REFERENCE_PERIOD_DESC is load-bearing for the same reason from
another direction: the identical short_desc is published at FIRST OF JUL and
END OF DEC, and those are real counts of the same herd that would splice in
without looking wrong.

NOTHING HERE TOUCHES THE NETWORK. The parsing tests feed the real dump's line
format through `_qualifies`/`_num`/`_period`, the one-pass test runs the real
scanning loop over a gzipped fixture with a fake `requests` injected, and the
write tests run against a recording fake cursor. A test that needed marsapi or
a 464MB download would not be run, and a guard nobody runs is worse than none.
"""
import gzip
import io
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


def _inv_row(short_desc, year, value, agg="NATIONAL", stat="INVENTORY",
             ref="FIRST OF JAN"):
    """One January 1 inventory line, at the real 1-indexed column numbers.

    FREQ_DESC is POINT IN TIME here, not ANNUAL. That is not a detail of the
    fixture: guessing "ANNUAL" by symmetry with the monthly price path selects
    nothing at all, which is why _qualifies_inventory does not test it.
    """
    f = [""] * 39
    f[job.COL_COMMODITY - 1] = "CATTLE"
    f[job.COL_STATISTICCAT - 1] = stat
    f[job.COL_SHORT_DESC - 1] = short_desc
    f[job.COL_AGG - 1] = agg
    f[job.COL_YEAR - 1] = str(year)
    f[job.COL_FREQ - 1] = "POINT IN TIME"
    f[job.COL_REF_PERIOD - 1] = ref
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


@pytest.mark.parametrize("fn_name", ["_qualifies", "_qualifies_inventory"])
def test_the_selection_compares_with_equality_not_membership(fn_name):
    """Pinned by AST as well as by behaviour. The behavioural test above passes
    for a dict lookup and fails for `in`; this one fails for any `in`/startswith
    comparison against a short_desc field reintroduced anywhere in the module,
    including in a helper the behavioural test does not route through."""
    tree = ast.parse((ROOT / "deploy" / "refresh_cattle_cycles.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    for node in ast.walk(fn):
        assert not isinstance(node, ast.Compare) or not any(
            isinstance(o, (ast.In, ast.NotIn)) for o in node.ops), (
            f"{fn_name} must select by exact short_desc, never by membership")
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("startswith", "endswith", "find"), node.attr


def test_only_national_monthly_rows_qualify():
    """A state or an annual row has the same short_desc and a different number."""
    assert job._qualifies(_row(GE500, 2026, 8, 1.0, agg="STATE")) is None
    assert job._qualifies(_row(GE500, 2026, 8, 1.0, freq="ANNUAL")) is None
    assert job._qualifies(_row(GE500, 2026, 8, 1.0)) == "cattle_ge500"


# -- the exact-short_desc rule, inventory -------------------------------------

BEEF_COWS = "CATTLE, COWS, BEEF - INVENTORY"
ALL_CATTLE = "CATTLE, INCL CALVES - INVENTORY"


def test_the_inventory_substring_trap_is_still_live():
    """If these ever stop colliding the trap is gone -- but so is the reason
    the tests below it exist, so check before deleting any of them."""
    assert set(job.INVENTORY_SERIES) == {BEEF_COWS, ALL_CATTLE}
    for near in job.COLLIDING_INVENTORY_SHORT_DESCS:
        assert near.startswith(ALL_CATTLE) and near != ALL_CATTLE
        assert near not in job.INVENTORY_SERIES


def test_a_dollar_valued_near_miss_is_rejected_by_the_fetcher():
    """THE WORST CASE ON THE PAGE. These carry dollars over the same 160 years
    with the same aggregation, statisticcat, reference period and domain, so
    every filter but the exact short_desc admits them -- and 2026 is 86,155,300
    head against $207,540,308,000, which charts as head."""
    assert job._qualifies_inventory(_inv_row(ALL_CATTLE, 2026, 86155300)) \
        == "all_cattle"
    for near in job.COLLIDING_INVENTORY_SHORT_DESCS:
        assert job._qualifies_inventory(_inv_row(near, 2026, 207540308000)) is None


def test_the_reference_period_is_load_bearing():
    """The SAME short_desc is published at FIRST OF JUL and END OF DEC. Those
    are real head counts of the same herd at another moment, so admitting them
    does not produce an obviously wrong chart -- it produces a January series
    with a midsummer count spliced into half of it."""
    assert job._qualifies_inventory(_inv_row(BEEF_COWS, 2026, 27607200)) \
        == "beef_cows"
    assert job._qualifies_inventory(
        _inv_row(BEEF_COWS, 2026, 1.0, ref="FIRST OF JUL")) is None
    assert job._qualifies_inventory(
        _inv_row(BEEF_COWS, 2026, 1.0, ref="END OF DEC")) is None


def test_only_national_inventory_rows_qualify():
    assert job._qualifies_inventory(
        _inv_row(BEEF_COWS, 2026, 1.0, agg="STATE")) is None
    assert job._qualifies_inventory(
        _inv_row(BEEF_COWS, 2026, 1.0, stat="SALES")) is None


def test_a_price_row_and_an_inventory_row_do_not_cross_selectors():
    """Each selector must reject the other kind outright, or one pass over the
    dump would write a price into the herd series or the reverse."""
    assert job._qualifies(_inv_row(BEEF_COWS, 2026, 1.0)) is None
    assert job._qualifies_inventory(_row(GE500, 2026, 8, 1.0)) is None


# -- the period key is a YEAR, not a month ------------------------------------

def test_the_inventory_period_is_the_bare_year():
    """NOT "YYYY-01". cycles.inventory() indexes these by int(year) precisely
    so nobody can line a Jan 1 count up against a monthly price series and
    difference the two; a "2026-01" key would read as a month and would sort
    into the price series own period space."""
    assert job._year("2026") == "2026"
    assert job._year("1867") == "1867"
    assert job._year("") is None and job._year("NA") is None
    assert job._year("1700") is None and job._year("2300") is None


def test_the_seed_stores_inventory_years_as_bare_string_keys(seed):
    for key in cycles.INVENTORY:
        rows = seed["inventory"][key]["rows"]
        assert all(k.isdigit() and len(k) == 4 for k in rows), key


def test_a_written_inventory_row_carries_a_bare_year_as_its_PERIOD(seed):
    """PERIOD is a string in Snowflake, so a year fits beside a "YYYY-MM"
    price. Nothing can collide because the series names differ."""
    rows = job.pending({}, {}, {k: seed["inventory"][k]["rows"]
                              for k in cycles.INVENTORY}, {})
    assert rows and all(len(r[1]) == 4 and r[1].isdigit() for r in rows)
    assert {r[0] for r in rows} == set(cycles.INVENTORY)
    assert {r[4] for r in rows} == {"nass"}
    assert {r[3] for r in rows} == set(job.INVENTORY_SERIES)


# -- one pass collects both ---------------------------------------------------

class _FakeResp:
    def __init__(self, blob):
        self.raw = io.BytesIO(blob)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass


class _FakeRequests:
    def __init__(self, blob):
        self.blob, self.calls = blob, 0

    def get(self, url, **kw):
        self.calls += 1
        return _FakeResp(self.blob)


def _dump(rows):
    body = "\t".join(f"C{i}" for i in range(1, 40)) + "\n"
    body += "".join("\t".join(r) + "\n" for r in rows)
    return gzip.compress(body.encode("utf-8"))


def _run_fetch(monkeypatch, rows):
    fake = _FakeRequests(_dump(rows))
    monkeypatch.setitem(sys.modules, "requests", fake)
    prices, inv = job.fetch_nass("http://example.invalid/x.txt.gz", verbose=False)
    return prices, inv, fake


def test_one_pass_over_the_dump_collects_prices_AND_inventory(monkeypatch):
    """A second pass would mean downloading 464MB again for 267 numbers. This
    runs the real scanning loop; `requests` is faked, the parsing is not."""
    rows = [_row(GE500, 2026, 7, 251.0), _row(GE500, 2026, 8, 252.0),
            _inv_row(BEEF_COWS, 2026, 27607200),
            _inv_row(ALL_CATTLE, 2026, 86155300),
            _inv_row(ALL_CATTLE, 2025, 86472200)]
    prices, inv, fake = _run_fetch(monkeypatch, rows)
    assert fake.calls == 1, "the dump must be streamed once, not once per kind"
    assert prices["cattle_ge500"] == {"2026-07": 251.0, "2026-08": 252.0}
    assert inv["beef_cows"] == {"2026": 27607200.0}
    assert inv["all_cattle"] == {"2025": 86472200.0, "2026": 86155300.0}


def test_the_scan_rejects_the_near_misses_it_streams_past(monkeypatch):
    """End to end rather than through the selector: the rows that would merge
    are IN the fixture, laid out exactly as the dump serves them."""
    rows = [_inv_row(ALL_CATTLE, 2026, 86155300),
            _inv_row(job.COLLIDING_INVENTORY_SHORT_DESCS[0], 2026, 207540308000),
            _inv_row(job.COLLIDING_INVENTORY_SHORT_DESCS[1], 2026, 2409),
            _inv_row(ALL_CATTLE, 2026, 1.0, ref="FIRST OF JUL"),
            _row(job.COLLIDING_SHORT_DESC, 2026, 8, 999.0)]
    prices, inv, _ = _run_fetch(monkeypatch, rows)
    assert inv["all_cattle"] == {"2026": 86155300.0}
    assert prices["cattle_ge500"] == {}


def test_two_values_for_one_year_raises_rather_than_overwriting(monkeypatch):
    """The one inventory failure with no symptom: the count stays 107 whichever
    row lands last, and a July count or a dollar value charts perfectly under a
    label saying January head. There are zero collisions in the live dump, so
    raising costs nothing until a filter stops working."""
    rows = [_inv_row(BEEF_COWS, 2026, 27607200),
            _inv_row(BEEF_COWS, 2026, 31000000)]
    with pytest.raises(RuntimeError) as e:
        _run_fetch(monkeypatch, rows)
    assert "two different values" in str(e.value)


def test_an_identical_repeat_is_not_treated_as_a_collision(monkeypatch):
    """Only a DISAGREEMENT is evidence of a broken filter."""
    rows = [_inv_row(BEEF_COWS, 2026, 27607200),
            _inv_row(BEEF_COWS, 2026, 27607200)]
    _prices, inv, _ = _run_fetch(monkeypatch, rows)
    assert inv["beef_cows"] == {"2026": 27607200.0}


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

def _fetched(seed):
    """What a healthy fetch returns, taken off the committed seed."""
    return ({k: dict(seed["series"][k]["rows"]) for k in cycles.SERIES},
            dict(seed["cpi_u"]["rows"]),
            {k: dict(seed["inventory"][k]["rows"]) for k in cycles.INVENTORY})


def test_describe_years_reports_the_span_and_the_count(seed):
    """first and last are INTS here where describe() returns string periods --
    the committed file stores them that way and cycles.inventory() indexes on
    int(year), so a string would sort "1867" beside "2026" lexicographically."""
    d = job.describe_years(seed["inventory"]["beef_cows"]["rows"])
    assert d == {"first": 1920, "last": 2026, "n": 107}
    assert isinstance(d["first"], int) and isinstance(d["last"], int)
    assert job.describe_years({}) == {"first": None, "last": None, "n": 0}


def test_both_inventory_series_are_contiguous(seed):
    """A gap shows as n below the span; there is no `missing` list on these
    blocks, so these three figures are the whole gap report."""
    for key in cycles.INVENTORY:
        d = job.describe_years(seed["inventory"][key]["rows"])
        assert d["n"] == d["last"] - d["first"] + 1, key


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
    prices, cpi, inv = _fetched(seed)
    built = job.seed_payload(prices, cpi, inv, seed)
    on_disk = json.loads(cycles.DATA.read_text(encoding="utf-8"))
    assert json.dumps(built, sort_keys=True) == json.dumps(on_disk, sort_keys=True)
    # Named explicitly, because the round trip above would also pass if the
    # inventory were carried over from `seed` rather than rebuilt -- which is
    # exactly the stopgap this change removed.
    assert built["inventory"]["beef_cows"]["n"] == 107
    assert built["inventory"]["all_cattle"]["first"] == 1867


def test_a_fetch_with_no_inventory_raises_rather_than_writing_a_seed(seed):
    """IT USED TO CARRY THE PREVIOUS FILE'S BLOCK OVER. That was right while
    this job did not fetch inventory; now it would hide the failure it was
    added to prevent -- a scan matching no inventory rows would write a seed
    whose herd half was last year's, with every count in it still plausible.
    The page reads this file whenever Snowflake is unreachable."""
    prices, cpi, inv = _fetched(seed)
    with pytest.raises(ValueError) as e:
        job.seed_payload(prices, cpi, {}, seed)
    assert "inventory" in str(e.value)
    # One series missing is just as fatal as both: the view offers a choice of
    # two and a key that is absent renders nothing with nothing raising.
    with pytest.raises(ValueError):
        job.seed_payload(prices, cpi, {"beef_cows": inv["beef_cows"]}, seed)


def test_the_carry_over_stopgap_is_gone():
    """Pinned so it cannot come back by habit when somebody adds a fourth
    series: a rebuild that reads the previous file for a block it is supposed
    to fetch reports a stale series as a fresh one."""
    tree = ast.parse((ROOT / "deploy" / "refresh_cattle_cycles.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "seed_payload")
    for node in ast.walk(fn):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            assert node.slice.value != "inventory", (
                "seed_payload must build the inventory block from the fetch, "
                "never read it off the file it is replacing")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args \
                and isinstance(node.args[0], ast.Constant):
            assert node.args[0].value != "inventory", node.args[0].value


# -- idempotency of the write -------------------------------------------------

def test_an_unchanged_period_is_not_written(seed):
    """The whole reason the schedule can be blunt: the catch-up run fetches
    both feeds and writes nothing."""
    prices, cpi, inv = _fetched(seed)
    first = job.pending(prices, cpi, inv, {})
    assert len(first) == (sum(len(v) for v in prices.values()) + len(cpi)
                          + sum(len(v) for v in inv.values()))
    have = {(r[0], r[1]): r[2] for r in first}
    assert job.pending(prices, cpi, inv, have) == []


def test_a_revised_period_IS_written(seed):
    """NASS restates price received, so an existing period changing is normal
    and is exactly what must be written -- append-only keeps the superseded
    figure rather than burying it."""
    prices, cpi, inv = _fetched(seed)
    have = _have(prices, cpi, inv)
    assert job.pending(prices, cpi, inv, have) == []
    prices["cows"]["2026-08"] = prices["cows"]["2026-08"] + 0.4
    out = job.pending(prices, cpi, inv, have)
    assert [(r[0], r[1]) for r in out] == [("cows", "2026-08")]


def test_a_revised_inventory_year_IS_written(seed):
    """USDA restates the January count against the following year, so a year
    already in the table moving is the normal case here rather than the
    alarming one -- append-only keeps the superseded figure."""
    prices, cpi, inv = _fetched(seed)
    have = _have(prices, cpi, inv)
    inv["beef_cows"]["2026"] = inv["beef_cows"]["2026"] + 50000
    out = job.pending(prices, cpi, inv, have)
    assert [(r[0], r[1]) for r in out] == [("beef_cows", "2026")]


def test_a_new_january_count_is_written(seed):
    prices, cpi, inv = _fetched(seed)
    have = _have(prices, cpi, inv)
    inv["all_cattle"]["2027"] = 85000000.0
    out = job.pending(prices, cpi, inv, have)
    assert [(r[0], r[1]) for r in out] == [("all_cattle", "2027")]


def _have(prices, cpi, inv):
    have = {(k, p): v for k, rows in prices.items() for p, v in rows.items()}
    have.update({(k, p): v for k, rows in inv.items() for p, v in rows.items()})
    have.update({(job.CPI_KEY, p): v for p, v in cpi.items()})
    return have


def test_a_new_month_is_written(seed):
    prices, cpi, inv = _fetched(seed)
    have = _have(prices, cpi, inv)
    prices["calves"]["2026-09"] = 420.0
    cpi["2026-10"] = 337.5
    out = {(r[0], r[1]) for r in job.pending(prices, cpi, inv, have)}
    assert out == {("calves", "2026-09"), (job.CPI_KEY, "2026-10")}


def test_every_written_row_carries_its_own_provenance(seed):
    """SHORT_DESC on the row is what makes the substring trap visible IN THE
    DATA rather than only in this file: two definitions merged upstream would
    show up as one series key carrying two short_descs."""
    prices, cpi, inv = _fetched(seed)
    rows = job.pending(prices, cpi, inv, {})
    by_key = {}
    for series, _period, _v, short_desc, source in rows:
        by_key.setdefault(series, set()).add((short_desc, source))
    for key in cycles.SERIES:
        assert len(by_key[key]) == 1, by_key[key]
        (desc, source), = by_key[key]
        assert source == "nass" and job.SERIES[desc] == key
    for key in cycles.INVENTORY:
        assert len(by_key[key]) == 1, by_key[key]
        (desc, source), = by_key[key]
        assert source == "nass" and job.INVENTORY_SERIES[desc] == key
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
    prices, cpi, inv = _fetched(seed)
    assert job._shortfall(prices, cpi, inv, seed) == []
    prices["calves"].pop("1970-01")
    assert any("calves" in s for s in job._shortfall(prices, cpi, inv, seed))
    prices["calves"]["1970-01"] = 1.0
    cpi.pop("1970-01")
    assert any(job.CPI_KEY in s for s in job._shortfall(prices, cpi, inv, seed))


def test_an_inventory_fetch_that_came_back_empty_is_a_failure(seed):
    """ELEVEN MONTHS OF THE YEAR A HEALTHY RUN WRITES NO INVENTORY AT ALL --
    USDA counts the herd once, on January 1. So "nothing new" cannot be read
    as a signal here, and a count against the seed is the only thing that
    separates a quiet month from a scan that matched no inventory rows."""
    prices, cpi, inv = _fetched(seed)
    empty = {k: {} for k in cycles.INVENTORY}
    bad = job._shortfall(prices, cpi, empty, seed)
    assert len(bad) == 2 and all("0 fetched vs" in s for s in bad)
    inv["beef_cows"].pop("1990")
    assert any("beef_cows" in s for s in job._shortfall(prices, cpi, inv, seed))


def test_the_shortfall_check_runs_before_the_seed_is_rewritten():
    """ORDER IS THE GUARD. Below the write, a truncated fetch would be written
    over the committed seed -- and that file is what the page falls back to
    whenever Snowflake is unreachable, so a bad run would quietly shorten the
    record for every reader rather than failing."""
    tree = ast.parse((ROOT / "deploy" / "refresh_cattle_cycles.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    check = min(n.lineno for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_shortfall")
    build = min(n.lineno for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "seed_payload")
    assert check < build


def test_a_longer_fetch_is_not_a_shortfall(seed):
    """The table is supposed to run AHEAD of the committed seed."""
    prices, cpi, inv = _fetched(seed)
    prices["cows"]["2026-09"] = 1.0
    cpi["2026-10"] = 1.0
    inv["beef_cows"]["2027"] = 1.0
    assert job._shortfall(prices, cpi, inv, seed) == []


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
    """Everything the refresh job writes: prices, CPI-U and the two January 1
    inventory series, the last with a bare year as PERIOD."""
    rows = [(k, p, v) for k in cycles.SERIES
            for p, v in seed["series"][k]["rows"].items()]
    rows += [(cycles.CPI_KEY, p, v) for p, v in seed["cpi_u"]["rows"].items()]
    rows += [(k, y, v) for k in cycles.INVENTORY
             for y, v in seed["inventory"][k]["rows"].items()]
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


def test_the_table_carries_the_herd_series_too(seed):
    """THE HALF-FAILURE THIS CHANGE EXISTS TO PREVENT. The herd view reads the
    inventory block and nothing else, so a Snowflake read that returned only
    prices took that view off the page while every price view went on working
    -- under a caption naming the live table."""
    d = cycles.load(_PageConn(rows=_table_rows(seed)))
    assert d["source"] == "snowflake"
    H = cycles.herd_summary(d)
    assert H and H["source"] == "snowflake"
    assert (H["first"], H["last"]) == (1920, 2026)
    # And the same answer as the file, since the rows are the same numbers.
    assert H["liquidations"] == cycles.herd_summary(cycles.load())["liquidations"]


def test_a_table_with_prices_but_no_inventory_falls_back_WHOLE(seed):
    """What the version of the job that fetched prices only leaves behind.
    Falling back costs the price advancement until the job has run once; the
    alternative is a view silently leaving the page, which reads as a feature
    nobody built rather than as a stale table."""
    rows = [r for r in _table_rows(seed) if r[0] not in cycles.INVENTORY]
    assert cycles.load(_PageConn(rows=rows))["source"] == "file"


def test_a_table_missing_ONE_inventory_series_falls_back(seed):
    """The view offers a choice of two and defaults to beef cows, so a missing
    all_cattle is invisible until somebody switches."""
    rows = [r for r in _table_rows(seed) if r[0] != "all_cattle"]
    assert cycles.load(_PageConn(rows=rows))["source"] == "file"


def test_the_table_advances_the_herd_view(seed):
    """A January count the committed seed does not have, keyed on a bare year
    beside prices keyed on YYYY-MM in the same column."""
    rows = _table_rows(seed, extra=[("beef_cows", "2027", 27000000.0),
                                    ("all_cattle", "2027", 85000000.0)])
    d = cycles.load(_PageConn(rows=rows))
    assert d["source"] == "snowflake"
    assert cycles.herd_summary(d)["last"] == 2027


def test_an_inventory_year_does_not_collide_with_a_price_period(seed):
    """PERIOD is one string column holding "2026" and "2026-08". Nothing can
    collide because the series names differ -- pinned so a future reader does
    not "tidy" the inventory key into YYYY-01 and merge the two spaces."""
    d = cycles.load(_PageConn(rows=_table_rows(seed)))
    assert set(d["inventory"]["beef_cows"]["rows"]) & \
        set(d["series"]["cows"]["rows"]) == set()
    assert all(len(p) == 4 for p in d["inventory"]["beef_cows"]["rows"])


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
