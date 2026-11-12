"""
One dead host must not cost the whole fetch.

Added 2026-11-12, after the letter page spun twice in a week. Ross: "why is my
daily cattle email just spinning when i click fetch latest data?"

`mpr.datamart.ams.usda.gov` was accepting connections and never answering.
Measured that morning, one fetch of the letter: 139s on the cash trade, 113s on
the week-to-date cash, 78s on the afternoon cutout -- 331 seconds of 488, spent
three times over on one host, because each fetcher independently waited out the
same timeout. Nothing raised out of the build; `_try` caught all three and the
run completed eight minutes later, by which time Community Cloud had dropped
the socket and the browser was showing a spinner that would never stop.

    python -m pytest tests/test_host_breaker.py -q
"""
import ast
import pathlib
import time
from datetime import date

import pytest
import requests

from letter import build, sources

REPO = pathlib.Path(__file__).resolve().parent.parent
DEAD = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports/2481"
ALIVE = "https://marsapi.ams.usda.gov/services/v1.2/reports/3658"


@pytest.fixture(autouse=True)
def _clean():
    sources.reset_hosts()
    yield
    sources.reset_hosts()


def _patch(monkeypatch, outcome):
    """
    Replace the BASE Session.request, which is what _BreakerSession's
    super().request() resolves to -- so the breaker's own logic is exercised
    rather than stubbed out.

    Returns a list that grows by one for every call that actually reaches it,
    which is the real claim: a skipped call never touches the network.
    """
    calls = []

    def fake(self, method, url, **kw):
        calls.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(requests.Session, "request", fake)
    return calls


# -- the breaker ------------------------------------------------------------

def test_the_second_call_to_a_dead_host_never_reaches_the_network(monkeypatch):
    """
    THE WHOLE POINT, and it is asserted by COUNTING rather than by timing.

    A wall-clock assertion would be the obvious one and it is the flaky one;
    what actually has to be true is that the request is never made, which is
    the only thing that can save the eight minutes.
    """
    calls = _patch(monkeypatch, requests.exceptions.ConnectionError("refused"))

    with pytest.raises(requests.exceptions.ConnectionError):
        sources._session().get(DEAD, timeout=5)
    assert len(calls) == 1

    with pytest.raises(sources.HostUnreachable):
        sources._session().get(DEAD, timeout=5)
    assert len(calls) == 1, "the second call went to the network anyway"


def test_the_skip_is_immediate(monkeypatch):
    """Generous bound -- the claim above is the count; this one is the symptom."""
    _patch(monkeypatch, requests.exceptions.ConnectionError("refused"))
    with pytest.raises(requests.exceptions.ConnectionError):
        sources._session().get(DEAD, timeout=5)

    t0 = time.perf_counter()
    with pytest.raises(sources.HostUnreachable):
        sources._session().get(DEAD, timeout=5)
    assert time.perf_counter() - t0 < 0.5


def test_a_read_timeout_trips_it_too(monkeypatch):
    """
    What USDA actually did: accept the connection, then never answer. Through
    the retrying adapter that surfaced as ConnectionError; against a plain
    request it is a ReadTimeout, and both mean no usable response.
    """
    calls = _patch(monkeypatch, requests.exceptions.ReadTimeout("no answer"))
    with pytest.raises(requests.exceptions.Timeout):
        sources._session().get(DEAD, timeout=5)
    with pytest.raises(sources.HostUnreachable):
        sources._session().get(DEAD, timeout=5)
    assert len(calls) == 1


def test_an_http_status_does_NOT_trip_it(monkeypatch):
    """
    THE SAFETY OF THE WHOLE THING, and the easy mistake.

    `Retry` carries a status_forcelist, so one report answering 500 four times
    surfaces as RetryError -- which says that endpoint is unwell and says
    nothing whatever about the host. Condemning the host on it would skip the
    afternoon cutout because the cash report was sick.
    """
    calls = _patch(monkeypatch, requests.exceptions.RetryError("too many 500s"))

    with pytest.raises(requests.exceptions.RetryError):
        sources._session().get(DEAD, timeout=5)
    assert sources.hosts_down() == [], "an HTTP status condemned the host"

    with pytest.raises(requests.exceptions.RetryError):
        sources._session().get(DEAD, timeout=5)
    assert len(calls) == 2, "the second call was skipped on a status failure"


def test_a_404_leaves_it_alone(monkeypatch):
    """A response is a response. requests does not raise on one, so nor do we."""
    resp = requests.Response()
    resp.status_code = 404
    _patch(monkeypatch, resp)
    assert sources._session().get(DEAD, timeout=5).status_code == 404
    assert sources.hosts_down() == []


def test_one_dead_host_does_not_condemn_another(monkeypatch):
    """
    The run that found this had marsapi and www.ams answering in about three
    seconds while the datamart hung -- same outage, same minute, same Akamai
    address. A breaker that took the whole of AMS down with it would have cost
    the slaughter, the carcass weights and the morning cutout for nothing.
    """
    seen = []

    def fake(self, method, url, **kw):
        seen.append(url)
        if "datamart" in url:
            raise requests.exceptions.ConnectionError("refused")
        resp = requests.Response()
        resp.status_code = 200
        return resp

    monkeypatch.setattr(requests.Session, "request", fake)

    with pytest.raises(requests.exceptions.ConnectionError):
        sources._session().get(DEAD, timeout=5)
    assert sources._session().get(ALIVE, timeout=5).status_code == 200
    assert sources.hosts_down() == ["mpr.datamart.ams.usda.gov"]
    assert ALIVE in seen


def test_reset_hosts_clears_it(monkeypatch):
    _patch(monkeypatch, requests.exceptions.ConnectionError("refused"))
    with pytest.raises(requests.exceptions.ConnectionError):
        sources._session().get(DEAD, timeout=5)
    assert sources.hosts_down()
    sources.reset_hosts()
    assert sources.hosts_down() == []


def test_the_trip_expires(monkeypatch):
    """
    The TTL is the backstop for callers that are not gather() -- the headline
    panel uses this session too. Without it a host that failed at breakfast
    would still be refused at four o'clock.

    THE BEHAVIOURAL HALF CANNOT CATCH AN INFINITE TTL, and the mutation
    harness is what proved it. Ageing the trip by `HOST_DOWN_TTL + 1` scales
    the offset with the constant, so the trip expires however large that
    constant is: setting it to 1e12 -- a breaker that never releases a host
    again -- passed this test untouched. The BOUND therefore gets its own
    assertion, and the band is the judgement rather than the number: long
    enough to cover one fetch, short enough that a recovered host is not
    refused for the rest of the afternoon.
    """
    assert 30 <= sources.HOST_DOWN_TTL <= 600, (
        f"HOST_DOWN_TTL is {sources.HOST_DOWN_TTL}s -- a breaker that outlives "
        f"the outage it was written for")

    calls = _patch(monkeypatch, requests.exceptions.ConnectionError("refused"))
    with pytest.raises(requests.exceptions.ConnectionError):
        sources._session().get(DEAD, timeout=5)

    sources._HOST_DOWN["mpr.datamart.ams.usda.gov"] -= sources.HOST_DOWN_TTL + 1
    assert sources.hosts_down() == []
    with pytest.raises(requests.exceptions.ConnectionError):
        sources._session().get(DEAD, timeout=5)
    assert len(calls) == 2, "an expired trip still skipped the call"


# -- it has to reach the page -----------------------------------------------

def test_the_skip_is_reported_rather_than_swallowed(monkeypatch):
    """
    HostUnreachable subclasses ConnectionError so build._try handles it like
    any other dead source: one line in the errors list, and the fetch carries
    on to everything that is still up.
    """
    assert issubclass(sources.HostUnreachable, requests.exceptions.ConnectionError)

    _patch(monkeypatch, requests.exceptions.ConnectionError("refused"))
    errors = []
    build._try("cash trade", lambda: sources._session().get(DEAD, timeout=5), errors)
    build._try("boxed beef", lambda: sources._session().get(DEAD, timeout=5), errors)
    assert len(errors) == 2
    assert "HostUnreachable" in errors[1] and "mpr.datamart.ams.usda.gov" in errors[1]


def test_the_page_names_the_host_once(monkeypatch):
    """
    Every call that hit it has already appended a line, and the first is a raw
    urllib3 "Max retries exceeded" -- true, unreadable, and silent about which
    figures are now missing.
    """
    _patch(monkeypatch, requests.exceptions.ConnectionError("refused"))
    with pytest.raises(requests.exceptions.ConnectionError):
        sources._session().get(DEAD, timeout=5)

    errors = []
    build.report_source_health({"cutout": {}}, date(2026, 11, 12), "recap", errors)
    named = [e for e in errors if e.startswith("mpr.datamart.ams.usda.gov")]
    assert len(named) == 1, errors
    assert "cash trade" in named[0] and "afternoon cutout" in named[0]


def test_nothing_is_said_when_every_host_answered():
    """A panel that cries every morning stops being read on the one morning."""
    errors = []
    build.report_source_health({"cutout": {}}, date(2026, 11, 12), "recap", errors)
    assert not [e for e in errors if "did not respond" in e]


# -- the reset is gather's first act ----------------------------------------

def test_gather_resets_the_breaker_before_it_fetches_anything():
    """
    Module state, so without the reset a host that failed at breakfast is
    still refused at four o'clock -- and the TTL alone would make that a
    two-minute window rather than a per-run one.

    BY AST, AND BY POSITION. `sources.reset_hosts()` has to precede every
    `_try` in gather(), not merely appear somewhere in it.
    """
    tree = ast.parse((REPO / "letter" / "build.py").read_text(encoding="utf-8"))
    gather = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "gather")

    resets = [n.lineno for n in ast.walk(gather)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == "reset_hosts"]
    tries = [n.lineno for n in ast.walk(gather)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_try"]

    assert resets, "gather() never resets the host breaker"
    assert tries, "gather() fetches nothing -- this test is looking at the wrong function"
    assert min(resets) < min(tries), (
        f"reset_hosts() at line {min(resets)} runs after the first _try at {min(tries)}")
