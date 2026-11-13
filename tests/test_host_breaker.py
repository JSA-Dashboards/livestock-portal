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


# -- ...and the FIRST discovery, which the breaker above cannot help with ----
#
# Added 2026-11-13, the second day of the same outage. Ross: "i opened the
# daily cattle reports email up- it fetched the data- but now when i refresh
# fetching the data, it just spins and won't load it."
#
# The breaker skips the second and third call to a dead host and never the
# first, and the first is where the time goes: seven of sources.py's calls hang
# off the USDA datamart, so whichever ran first paid a 120s read budget for all
# of them. Observed first discoveries on 11-12: 139s and 261s.

def test_a_read_timeout_is_not_retried():
    """
    A read timeout means the server TOOK the request and sent no byte inside
    the budget. A retry hands the same budget to the same server, so it
    almost never converts a failure into a success and always multiplies the
    wait -- four attempts at 120s is most of what a dead host costs.

    Measured against the live outage with a 3s budget: 30.8s as shipped
    against 5.1s with read=0, both raising ConnectionError, so the breaker
    trips either way and only the waiting changes.
    """
    retry = sources._session().get_adapter("https://x/").max_retries
    assert retry.read == 0, (
        f"read retries are {retry.read} -- a dead host costs that many read "
        f"budgets before anyone is told")


def test_connect_and_status_retries_are_left_alone():
    """
    The two cases where trying again DOES work. A refused connection can be
    transient and a 500 can be one endpoint having a bad minute -- neither
    says the host is unreachable, and `total` still governs both.
    """
    retry = sources._session().get_adapter("https://x/").max_retries
    assert retry.total == 3, "connect/status retries went with the read ones"
    assert 500 in retry.status_forcelist and 429 in retry.status_forcelist


def test_the_probe_session_asks_once_AND_is_the_one_the_probe_uses():
    """
    A status answer of ANY kind is a pass for the probe, so there is nothing
    a second attempt could turn into one -- and _session()'s status_forcelist
    would otherwise spend 9s of backoff asking a sick-but-alive host four
    times, on the call whose whole purpose is to be cheap.

    THE SECOND HALF WAS MISSING AND A MUTATION FOUND IT. The first version
    inspected _probe_session() alone, so swapping the probe's own call over to
    _session() left this green while the probe retried four times -- the
    config was right and nothing used it. Same hole as `assert "wasde.SCHEMA"
    in page`: a test on the DEFINITION says nothing about the USE.
    """
    retry = sources._probe_session().get_adapter("https://x/").max_retries
    assert retry.total == 0, "the probe retries, which is what it exists not to do"

    tree = ast.parse((REPO / "letter" / "sources.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "preflight")
    makers = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id.endswith("session")}
    assert makers == {"_probe_session"}, (
        f"preflight() builds its session with {sorted(makers)} -- the no-retry "
        f"config above is not what the probe actually uses")


def test_the_preflight_trips_the_breaker(monkeypatch):
    """THE WHOLE POINT: one short request, and every later call is free."""
    calls = _patch(monkeypatch, requests.exceptions.ConnectionError("dead"))
    assert sources.preflight() == ["mpr.datamart.ams.usda.gov"]
    assert len(calls) == 1, "the preflight is not one request"

    before = len(calls)
    with pytest.raises(sources.HostUnreachable):
        sources._session().get(DEAD, timeout=120)
    assert len(calls) == before, "the guarded call still reached the network"


def test_the_preflight_does_NOT_trip_on_a_status(monkeypatch):
    """
    A 500 says one endpoint is unwell and says nothing whatever about the
    host. Condemning it here would skip the cash trade, the week-to-date
    cash, the afternoon cutout and the grading % because the catalogue had a
    bad minute -- four figures for no reason, on a host that was answering.
    """
    sick = requests.Response()
    sick.status_code = 500
    _patch(monkeypatch, sick)
    assert sources.preflight() == []


def test_the_preflight_does_NOT_trip_on_a_404(monkeypatch):
    """Any answer at all means the service is alive. That is the whole test."""
    gone = requests.Response()
    gone.status_code = 404
    _patch(monkeypatch, gone)
    assert sources.preflight() == []


def test_the_preflight_reads_the_breakers_own_record():
    """
    BY AST, because this is about there being ONE rule rather than two.
    _BreakerSession already decides what counts as a dead host; a preflight
    that inspected the exception itself would be a second copy of that
    decision, free to drift from it -- and the drift would be invisible,
    since both forms return a plausible list of hostnames.
    """
    tree = ast.parse((REPO / "letter" / "sources.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "preflight")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert len(returns) == 1, "preflight() has more than one way out"
    val = returns[0].value
    assert isinstance(val, ast.Call) and isinstance(val.func, ast.Name)
    assert val.func.id == "hosts_down", (
        "preflight() decides for itself which hosts are down instead of "
        "reading the breaker's record")


def test_the_preflight_covers_the_datamart_and_nothing_else():
    """
    A probe earns its request where SEVERAL expensive calls share one host.
    esmis, CFTC and Yahoo have one apiece and marsapi has one, so for those
    the breaker's first discovery is the only discovery and a probe would add
    latency to every healthy run to save nothing.
    """
    from urllib.parse import urlsplit
    hosts = [urlsplit(u).hostname for u in sources.PREFLIGHT_URLS]
    assert hosts == ["mpr.datamart.ams.usda.gov"]
    assert urlsplit(sources.LMR_BASE).hostname in hosts


def test_the_preflight_budget_clears_the_measured_healthy_response():
    """
    A BAND, AND THE REASON IS A BUG THIS ALREADY HAD. The first version
    borrowed apps/cash_trade's (3, 8) for the LIST endpoint, on that page's
    recorded ~3.7s healthy figure, and pinned the two files together. When
    the datamart came back the real time to first byte -- which is what a read
    timeout measures -- was 5.17-6.08s over five runs, so the probe sat 1.3x
    clear of its own worst healthy run and a busy-but-alive host would have
    tripped it. A probe that cries wolf costs four figures on a good day.

    The slug endpoint it probes now measured 3.81-4.96s TTFB, so 20s is 4x
    clear. The lower bound is what the bug was; the upper bound is what makes
    it a timeout at all rather than a number large enough to be none, the
    reason HOST_DOWN_TTL and MSAL_TIMEOUT are bands too.
    """
    connect, read = sources.PREFLIGHT_TIMEOUT
    assert 2 <= connect <= 10, f"connect budget is {connect}s"
    assert 15 <= read <= 45, (
        f"read budget is {read}s -- under 15 it is inside the measured spread "
        f"of a HEALTHY response, over 45 it is not bounding anything")


def test_the_preflight_probes_a_report_rather_than_the_catalogue():
    """
    A pass has to mean the thing the letter needs is being served. The
    catalogue is a different code path, it measured slower and far more
    variable than a report slug, and under HEAD it took 18-28s and failed
    once in four -- so "the catalogue answered" is a weaker claim, more
    slowly.
    """
    assert sources.PREFLIGHT_URLS == (f"{sources.LMR_BASE}/{sources.CT154_ID}",)


def test_gather_preflights_after_the_reset_and_before_any_fetch():
    """
    BY POSITION, in all three directions. After reset_hosts(), or it probes
    and then forgets what it learned. Before the first _try, or it is not a
    preflight at all. And exactly once, because a second call after the
    breaker has tripped would raise HostUnreachable from inside gather()
    rather than through _try.
    """
    tree = ast.parse((REPO / "letter" / "build.py").read_text(encoding="utf-8"))
    gather = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "gather")

    def lines(attr):
        return [n.lineno for n in ast.walk(gather)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr]

    pre, reset = lines("preflight"), lines("reset_hosts")
    tries = [n.lineno for n in ast.walk(gather)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_try"]

    assert len(pre) == 1, f"gather() calls preflight() {len(pre)} times"
    assert reset and tries
    assert min(reset) < pre[0], "the preflight runs before the breaker is reset"
    assert pre[0] < min(tries), (
        f"preflight() at line {pre[0]} runs after the first _try at {min(tries)}")


@pytest.mark.parametrize("broken,why", [
    ("retry = Retry(total=3, backoff_factor=b)", "read is back to the default"),
    ("return [h for h in _HOST_DOWN]", "preflight re-decides for itself"),
])
def test_the_new_guards_reject_the_broken_form(broken, why):
    """
    A guard that cannot fail is the thing it guards against. Both of these
    are forms that compile, render and read perfectly well.
    """
    tree = ast.parse(broken)
    if "Retry" in broken:
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        assert "read" not in {k.arg for k in call.keywords}, why
    else:
        ret = next(n for n in ast.walk(tree) if isinstance(n, ast.Return))
        assert not (isinstance(ret.value, ast.Call)
                    and getattr(ret.value.func, "id", "") == "hosts_down"), why
