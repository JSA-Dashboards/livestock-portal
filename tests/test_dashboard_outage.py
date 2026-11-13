"""
A dead host must not be cached as an empty dashboard.

Added 2026-11-13, after mpr.datamart.ams.usda.gov spent two working days
accepting connections and never answering. The letter was fixed first; this is
the dashboards, and their exposure was far worse than the letter's:

    page             worst case, ONE load     poisoning sites
    beef_cutout      ~3h  (17.6h reachable)   4
    beef_trimmings   ~49m                     5
    cash_trade       ~8m  (33m on a tab)      3

THE SLOW WAIT WAS NOT THE WORST OF IT. Several of these pages fetch a batch of
independent reports concurrently and let a failed job yield [] rather than
raise -- sound reasoning, because USDA not publishing one report is no reason
to blank the other seven. But a dead HOST fails every job the same way, so the
same `except Exception` turned a whole-host outage into an empty frame, which
`@st.cache_data(persist="disk")` with NO ttl then held permanently: past the
end of the outage, surviving a reboot, until somebody pressed Refresh.

And the reader was told the wrong thing. "USDA published no daily reports for
these regions in this window" is a false claim ABOUT USDA, not a missing one
about us -- and the correct warning sat directly above it, already written,
already correctly ordered, and unreachable because nothing ever raised.

    python -m pytest tests/test_dashboard_outage.py -q
"""
from __future__ import annotations

import ast
import pathlib

import pytest
import requests

import http_breaker
from streamlit_source import load_from_app

REPO = pathlib.Path(__file__).resolve().parent.parent
CASH = REPO / "apps" / "cash_trade" / "app.py"
LEVERAGE = REPO / "apps" / "cash_trade" / "leverage.py"


# -- the one rule the swallow sites share ------------------------------------

@pytest.mark.parametrize("exc,is_host", [
    (requests.exceptions.ConnectionError("refused"), True),
    (requests.exceptions.ConnectTimeout("slow"), True),
    (requests.exceptions.ReadTimeout("stalled"), True),
    (http_breaker.HostUnreachable("skipped"), True),
    # A STATUS IS NOT A HOST. requests raises RetryError when a
    # status_forcelist is exhausted, and one endpoint answering 500 says
    # nothing whatever about the host -- condemning it there would blank the
    # cutout because the cash report was sick.
    (requests.exceptions.RetryError("500 x4"), False),
    (requests.exceptions.HTTPError("500"), False),
    (ValueError("bad json"), False),
    (KeyError("results"), False),
])
def test_host_failures_are_told_apart_from_report_failures(exc, is_host):
    assert http_breaker.is_connection_failure(exc) is is_host


# -- the premise the whole design rests on -----------------------------------

def test_streamlit_caches_a_returned_sentinel_and_not_a_raised_error():
    """
    MEASURED, NOT ASSUMED, because everything above depends on it: a cached
    loader that RAISES stores nothing, so the next rerun tries again, while one
    that catches and returns a value stores THAT. Which is why the fix is to
    let the failure escape rather than to shorten a ttl.

    Local Streamlit is 1.63 and the deployed app installs whatever is current
    at reboot time (1.67.0 as of 2026-11-05), so this pins the behaviour the
    design assumes rather than trusting a version nobody controls.
    """
    import streamlit as st

    ran = {"raise": 0, "sentinel": 0}

    @st.cache_data(ttl=3600)
    def _raises():
        ran["raise"] += 1
        raise requests.exceptions.ConnectionError("host down")

    @st.cache_data(ttl=3600)
    def _swallows():
        ran["sentinel"] += 1
        try:
            raise requests.exceptions.ConnectionError("host down")
        except requests.exceptions.ConnectionError:
            return "EMPTY"

    for _ in range(3):
        with pytest.raises(requests.exceptions.ConnectionError):
            _raises()
        _swallows()

    assert ran["raise"] == 3, "st.cache_data cached an exception -- the fix is void"
    assert ran["sentinel"] == 1, "a returned sentinel was NOT cached"


# -- cash_trade's batch worker -----------------------------------------------

def _fetch_many(raiser):
    """
    Lift _fetch_many out of the page with a stub session, so the real
    try/except runs rather than a copy of it.
    """
    class _Resp:
        status_code = 200

        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {"results": [{"ok": 1}]}

    class _Sess:
        def get(self, url, **kw):
            exc = raiser(url)
            if exc is not None:
                raise exc
            return _Resp()

    from concurrent.futures import ThreadPoolExecutor
    return load_from_app(
        CASH, "_fetch_many",
        globals_={"_session": lambda *a, **k: _Sess(),
                  "_daily_rows": lambda payload: payload["results"],
                  "LMR_BASE": "https://mpr.datamart.ams.usda.gov/x",
                  "http_breaker": http_breaker,
                  "ThreadPoolExecutor": ThreadPoolExecutor})


JOBS = [(f"k{i}", f"slug{i}", "Detail", {}) for i in range(4)]


def test_a_dead_host_propagates_out_of_the_batch():
    """
    THE WHOLE FIX. Every job fails the same way on a dead host, so swallowing
    them returned an empty frame that `persist="disk"` with no ttl then kept
    for ever. It has to escape the cached function, or nothing else matters.
    """
    fn = _fetch_many(lambda url: requests.exceptions.ConnectionError("dead"))
    with pytest.raises(requests.exceptions.ConnectionError):
        fn(JOBS)


def test_the_breakers_own_skip_propagates_too():
    """HostUnreachable subclasses ConnectionError precisely so this holds."""
    fn = _fetch_many(lambda url: http_breaker.HostUnreachable("skipped"))
    with pytest.raises(http_breaker.HostUnreachable):
        fn(JOBS)


def test_ONE_bad_report_is_still_swallowed():
    """
    The other half, and it is not a formality -- this is why the swallow was
    there. USDA genuinely does not publish every report every day, and one
    slug being down must not blank the other seven. A fix that re-raised
    everything would have broken the page on an ordinary Tuesday.
    """
    fn = _fetch_many(lambda url: ValueError("bad json") if url.endswith("slug2/Detail") else None)
    out = fn(JOBS)
    assert out["k2"] == [], "a single bad report should yield an empty list"
    assert out["k0"] == [{"ok": 1}] and out["k3"] == [{"ok": 1}], (
        "a bad report took its healthy siblings with it")


def test_an_http_status_is_still_swallowed():
    """A 500 on one endpoint says nothing about the host. Same rule as the
    breaker's own, and drawn in one place so the two cannot drift."""
    fn = _fetch_many(lambda url: requests.exceptions.RetryError("500 x4")
                     if url.endswith("slug1/Detail") else None)
    out = fn(JOBS)
    assert out["k1"] == []
    assert out["k0"] == [{"ok": 1}]


# -- leverage.py's five-section fetch ----------------------------------------

def test_leverage_propagates_a_dead_host_and_swallows_one_section():
    """
    The worse of cash_trade's three sites: five sections at a 180s timeout
    each, cached under persist="disk" with no ttl, and `lev_err` left EMPTY --
    so the page said nothing at all while serving five blank frames for ever.
    """
    import sys
    sys.path.insert(0, str(LEVERAGE.parent))
    import leverage

    class _Resp:
        status_code = 200

        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {"results": [{"ok": 1}]}

    jobs = [(f"k{i}", f"slug{i}", "Section") for i in range(3)]

    def factory(exc):
        class _S:
            def get(self, url, **kw):
                if exc is not None and "slug1" in url:
                    raise exc
                return _Resp()
        return lambda: _S()

    with pytest.raises(requests.exceptions.ConnectionError):
        leverage.fetch(factory(requests.exceptions.ConnectionError("dead")), jobs)

    out = leverage.fetch(factory(ValueError("bad json")), jobs)
    assert out["k1"] == [] and out["k0"] == [{"ok": 1}]


# -- the guard, scoped to the sites that have this shape ---------------------

WORKERS = [
    ("apps/cash_trade/app.py", "_fetch_many"),
    ("apps/cash_trade/leverage.py", "fetch"),
]


@pytest.mark.parametrize("rel,fname", WORKERS)
def test_every_batch_worker_tests_the_exception_before_swallowing(rel, fname):
    """
    SCOPED TO THESE FUNCTIONS, NOT REPO-WIDE, and deliberately. A rule saying
    "no `except Exception` may return a value" would reject dozens of places
    where swallowing is exactly right -- and this repo records what happens to
    a guard that rejects correct code: it gets deleted the first time it
    blocks somebody. These are the concurrent batch workers, where every job
    fails identically on a dead host, so they are the sites where the
    distinction has to be made.
    """
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8-sig"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == fname)
    # the inner worker, whichever it is called
    inner = [n for n in ast.walk(fn)
             if isinstance(n, ast.FunctionDef) and n is not fn]
    assert inner, f"{rel}:{fname} has no inner worker any more"

    for node in inner:
        handlers = [h for h in ast.walk(node) if isinstance(h, ast.ExceptHandler)]
        assert handlers, f"{rel}:{fname} swallows nothing -- has it been rewritten?"
        for h in handlers:
            dumped = ast.dump(ast.Module(body=h.body, type_ignores=[]))
            assert "is_connection_failure" in dumped, (
                f"{rel}:{fname} swallows without asking whether the HOST is "
                f"down -- a whole-host outage will be cached as an empty frame")
            assert "Raise" in dumped, (
                f"{rel}:{fname} tests for a host failure and then does not "
                f"re-raise it")


def test_the_guard_rejects_the_form_it_replaced():
    """A guard that cannot fail is the thing it guards against. This is the
    code as it stood this morning, in both files."""
    broken = ast.parse('''
def fetch(jobs):
    def run(job):
        try:
            return 1
        except Exception:
            return []
    return run
''')
    fn = next(n for n in ast.walk(broken)
              if isinstance(n, ast.FunctionDef) and n.name == "fetch")
    inner = [n for n in ast.walk(fn) if isinstance(n, ast.FunctionDef) and n is not fn]
    h = next(x for x in ast.walk(inner[0]) if isinstance(x, ast.ExceptHandler))
    dumped = ast.dump(ast.Module(body=h.body, type_ignores=[]))
    assert "is_connection_failure" not in dumped


# -- beef_cutout and beef_trimmings: loop-shaped swallows ---------------------

LOOPS = [
    ("apps/beef_cutout/app.py", "fetch_thin_sections"),
    ("apps/beef_cutout/app.py", "fetch_cut_sections"),
]


@pytest.mark.parametrize("rel,fname", LOOPS)
def test_every_per_item_swallow_asks_whether_the_host_is_down(rel, fname):
    """
    The same rule as the batch workers, in the shape these two use: a `for`
    over sections or years with the try INSIDE it, so one missing item is
    skipped. On a dead host every item is missing, so without the test these
    returned `{}` -- and `persist="disk"` with no ttl kept it permanently.

    fetch_cut_sections is the worst of the four sites in this repo: at the
    26-year setting its loop makes 52 calls, which on the old 300s budget was
    over seventeen hours, and the empty result was cached for ever.
    """
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8-sig"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == fname)
    handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
    assert handlers, f"{rel}:{fname} no longer swallows anything"
    for h in handlers:
        dumped = ast.dump(ast.Module(body=h.body, type_ignores=[]))
        assert "is_connection_failure" in dumped and "Raise" in dumped, (
            f"{rel}:{fname} swallows without asking whether the HOST is down")


def test_the_cutout_budget_clears_its_own_measured_response():
    """
    A BAND, for the reason the preflight's needed one -- and this is the third
    time today that a timeout turned out to be sized against nothing.

    Measured against the live host on 2026-11-13, time to first byte, which is
    what a read timeout governs: Summary 2.60-5.65s, Current Cutout Values
    3.64s, Current Volume 4.11s, Change From Prior Day 3.67s, Composite Primal
    Values 4.99-5.95s, Choice Cuts one year 3.74-5.52s. Worst of fourteen runs
    5.95s. The 300 this replaces was FIFTY times that, and with four attempts
    plus 18s of backoff it made one dead host cost 1,218s per call.

    The upper bound matters as much as the lower: 300 passed any test that
    merely asserted a timeout was set.
    """
    fn = load_from_app(REPO / "apps" / "beef_cutout" / "app.py", "_lmr_get",
                       consts=("LMR_TIMEOUT",),
                       globals_={"_lmr_session": lambda: None, "LMR_BASE": "",
                                 "REPORT_ID": 0, "pd": __import__("pandas")})
    import ast as _ast
    src = (REPO / "apps" / "beef_cutout" / "app.py").read_text(encoding="utf-8-sig")
    val = next(n.value for n in _ast.walk(_ast.parse(src))
               if isinstance(n, _ast.Assign) and len(n.targets) == 1
               and getattr(n.targets[0], "id", "") == "LMR_TIMEOUT")
    seconds = _ast.literal_eval(val)
    assert 20 <= seconds <= 120, (
        f"LMR_TIMEOUT is {seconds}s -- under 20 it is inside the measured "
        f"healthy spread, over 120 it is not bounding anything")
    assert fn is not None


def test_no_datamart_call_still_carries_the_old_300s_budget():
    """The constant is only worth having if nothing bypasses it."""
    src = (REPO / "apps" / "beef_cutout" / "app.py").read_text(encoding="utf-8-sig")
    assert "timeout=300" not in src


# -- beef_trimmings ----------------------------------------------------------

TRIM = REPO / "apps" / "beef_trimmings" / "app.py"


def test_an_empty_archive_pull_raises_rather_than_being_persisted():
    """
    THE ONE UNBOUNDED POISONING ON THAT PAGE, and it is not a host failure at
    all: AMS answers 200 with a payload carrying no usable rows -- the "200
    that means no" shape this repo documents for slug 2452 -- and the empty
    frame went into @st.cache_data(persist="disk") with NO ttl. That entry
    survives reruns and reboots, so the chart stays blank long after AMS
    recovers, with nothing saying why.
    """
    tree = ast.parse(TRIM.read_text(encoding="utf-8-sig"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_pull_xb401")
    raises = [n for n in ast.walk(fn) if isinstance(n, ast.Raise)]
    assert raises, "_pull_xb401 can still return an empty frame to a disk cache"


def test_the_archive_timeout_is_NOT_tightened():
    """
    A GUARD AGAINST A FIX, which is unusual and is the point. The obvious
    tidy-up is to bring this page's 180s into line with beef_cutout's 60 --
    and it would break the archive pull. Measured 2026-11-13, the 6,000-report
    LM_XB401 archive takes 16.21-31.18s to its FIRST BYTE, five to six times
    anything else on the datamart, so 180s is about 6x its worst healthy
    figure and earns its size. The per-call budget stopped mattering for an
    outage anyway once the preflight went in.

    BY AST AND SCOPED TO _pull_xb401, because a substring match let a
    mutation through: this page has TWO `timeout=180` calls -- the archive
    pull and fetch_us_weekly90 -- so `"timeout=180" in src` stayed true after
    the archive one was changed. The same hole as the cutout slide test caught
    earlier the same day: a match across two sites proves neither.
    """
    tree = ast.parse(TRIM.read_text(encoding="utf-8-sig"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_pull_xb401")
    timeouts = [ast.literal_eval(k.value) for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                for k in n.keywords if k.arg == "timeout"]
    assert len(timeouts) == 1, f"_pull_xb401 makes {len(timeouts)} timed calls"
    assert timeouts[0] >= 120, (
        f"the archive budget is {timeouts[0]}s -- re-measure its time to "
        f"first byte before deciding that is safe; it was 16.21-31.18s on a "
        f"HEALTHY host, five to six times anything else on the datamart")


def test_the_page_preflights_before_it_loads():
    """It has no publication probe to double as one, so it needed its own."""
    src = TRIM.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "_datamart_preflight"]
    assert fn, "beef_trimmings no longer preflights"
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_datamart_preflight"]
    assert len(calls) == 1, "the preflight is called {} times".format(len(calls))

    first_fetch = min(n.lineno for n in ast.walk(tree)
                      if isinstance(n, ast.Call)
                      and getattr(n.func, "id", "") in
                      ("fetch_us_fresh90", "fetch_import_cow90", "fetch_us_weekly90")
                      and n.lineno > fn[0].lineno)
    assert calls[0].lineno < first_fetch, (
        f"the preflight at line {calls[0].lineno} runs after the first fetch "
        f"at {first_fetch}")


def test_the_snowflake_connect_is_bounded():
    """
    login_timeout IS NOT A SOCKET TIMEOUT -- it is the connector's retry budget
    for authentication, consulted between attempts. socket_timeout and
    network_timeout both default to None (checked against connector 4.7.1's
    DEFAULT_CONFIGURATION), so this call had no duration bound at all while
    looking as though it had one.
    """
    tree = ast.parse(TRIM.read_text(encoding="utf-8-sig"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_sf_connect")
    kwargs = {k.arg for n in ast.walk(fn) if isinstance(n, ast.Call)
              for k in n.keywords if k.arg}
    assert "socket_timeout" in kwargs, "the Snowflake read is still unbounded"
