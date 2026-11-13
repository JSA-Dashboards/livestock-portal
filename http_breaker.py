"""
One dead host must not cost the whole page.

A USDA host that accepts the connection and then never answers is the failure
this module exists for. It is not hypothetical and it is not rare: on
2026-11-12 and again on 2026-11-13 `mpr.datamart.ams.usda.gov` did exactly
that, for most of a working day each time, while `marsapi.ams.usda.gov` on the
SAME Akamai address answered in 0.14s. Nothing was broken on our side, nothing
raised, and every page that reads that host hung for minutes.

AT THE REPO ROOT, AND ONE COPY, for the reason `wasde.py` is: Python caches
modules by NAME, so a second copy under an app directory would mean whichever
page loaded first decided which copy every other page got -- the
`snowflake_db.py`-times-five problem, which this repo already records. The
breaker also keeps STATE, so a second copy would be a second, disagreeing
record of which hosts are down. `tests/test_host_breaker.py` asserts
rglob("http_breaker.py") returns exactly one path.

It imports requests and nothing of this project's, so letter/, apps/ and
deploy/ can all use it.

    from http_breaker import session, probe_session, preflight, hosts_down


THE THREE PARTS, AND WHY NONE OF THEM IS ENOUGH ALONE
-----------------------------------------------------

1. THE BREAKER. The first connection-level failure records the HOST, and every
   later call to it inside the TTL raises HostUnreachable immediately instead
   of waiting out the same timeout again. Measured on the letter, 2026-11-12:
   three fetchers independently waited out one dead host for 139s, 113s and
   78s -- 331 seconds of a 488-second fetch, spent three times over.

2. read=0. A read timeout is not retried. It means the server TOOK the request
   and sent no byte inside the budget, so a retry hands the same budget to the
   same server: it almost never converts a failure into a success and always
   multiplies the wait. Measured against the live outage with a deliberately
   small 3s budget, so the experiment cost seconds instead of minutes:

       Retry(total=3)            30.8s
       Retry(total=3, read=0)     5.1s

   Both raise requests.ConnectionError, so the breaker trips either way; only
   the waiting changes. `total` still governs CONNECT failures and the
   status_forcelist, which are the two cases where trying again does work --
   DO NOT take those out with it.

3. preflight(). The breaker saves the SECOND and third discoveries and never
   the first, and the first is where the time goes when several expensive
   calls share one host. One short request up front, and the rest are free.


WHAT TRIPS IT, AND WHAT MUST NOT
---------------------------------

CONNECTION-LEVEL FAILURES ONLY, NEVER AN HTTP STATUS, and that distinction is
the whole safety of it. A `status_forcelist` exhaustion surfaces as
requests.RetryError, which says one endpoint is unwell and says nothing
whatever about the host; condemning the host on it would skip the cutout
because the cash report was sick. requests already draws the line for us --
ConnectionError (and ConnectTimeout, which subclasses both) for the connection
case, RetryError for the status one -- so the exception types are the rule and
there is no second rule to keep in step.

ONE FAILURE IS ENOUGH, because the adapter has already tried four times by
then. A false trip costs one run of missing figures and is recovered by the
TTL expiring or by an explicit reset_hosts(); the alternative costs minutes
every time.


THE INTERACTION WITH `@st.cache_data`, WHICH IS THE HALF THAT BITES
--------------------------------------------------------------------

A FAST FAILURE THAT GETS CACHED IS WORSE THAN A SLOW ONE, because it outlives
the outage. If a cached loader catches the failure and returns an empty frame
or a sentinel, Streamlit stores THAT -- and with `persist="disk"` (which voids
a ttl, as this repo documents in several places) it survives a reboot. The
page then renders "no data" for as long as the cache lives, on a host that
came back hours ago, with nothing saying why.

So a cached loader should let the failure ESCAPE: st.cache_data does not cache
an exception, so the next rerun tries again. That is only affordable because
of this module -- without the breaker every rerun would pay the full timeout,
and with it the retry is instant until the TTL lets one real attempt through.
The breaker is what makes "never cache a failure" cheap.
"""
import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__all__ = [
    "HOST_DOWN_TTL", "HostUnreachable", "BreakerSession",
    "reset_hosts", "hosts_down", "session", "probe_session", "preflight",
    "PROBE_TIMEOUT",
]

# How long a trip stands. Long enough that a burst of Streamlit reruns during
# an outage costs one discovery between them; short enough that a host coming
# back is picked up without anyone restarting anything.
HOST_DOWN_TTL = 120.0

# The probe budget. 20s is roughly 4x the worst healthy time-to-first-byte
# measured on the datamart's report endpoint (3.81-4.96s over five runs) --
# see preflight() for why that margin is the number that matters, and for the
# bug the first version of it had.
PROBE_TIMEOUT = (3, 20)

_HOST_DOWN: dict = {}


class HostUnreachable(requests.exceptions.ConnectionError):
    """
    Raised in place of re-waiting out a host that already failed.

    A ConnectionError SUBCLASS on purpose: every caller that already handles a
    dead host handles this unchanged, including the letter's `_try`, which
    reports whatever is raised and carries on.
    """


def reset_hosts() -> None:
    """
    Forget every tripped host.

    Call this at the start of a RUN that should get a fresh chance -- the
    letter's gather() does. A Streamlit page has no such boundary, so there
    the TTL is the only bound, which is what it is sized for.
    """
    _HOST_DOWN.clear()


def hosts_down() -> list:
    """The hosts tripped and not yet expired, for a caller to name."""
    now = time.monotonic()
    return sorted(h for h, t in _HOST_DOWN.items() if now - t < HOST_DOWN_TTL)


class BreakerSession(requests.Session):
    """
    A Session that refuses a host it has already seen fail.

    Subclassing rather than wrapping each call site: there are dozens across
    this repo and they all go through Session.request, so one override covers
    the ones written later too.
    """

    def request(self, method, url, **kw):
        host = urlsplit(url).hostname or ""
        failed_at = _HOST_DOWN.get(host)
        if failed_at is not None and time.monotonic() - failed_at < HOST_DOWN_TTL:
            raise HostUnreachable(
                f"{host} did not respond a moment ago, so this call was "
                f"skipped rather than waiting out the same timeout again")
        try:
            return super().request(method, url, **kw)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            # Recorded at the FAILURE, not at the attempt: a 120s read timeout
            # would otherwise start its own TTL two minutes in the past.
            if not isinstance(exc, HostUnreachable):
                _HOST_DOWN[host] = time.monotonic()
            raise


def session(backoff: float = 1.5, total: int = 3,
            status_forcelist=(429, 500, 502, 503, 504)) -> requests.Session:
    """A breaker-aware Session that does not retry read timeouts. See the
    module docstring for the measurement behind read=0."""
    s = BreakerSession()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=total, read=0, backoff_factor=backoff,
        status_forcelist=list(status_forcelist), allowed_methods=["GET"])))
    return s


def probe_session() -> requests.Session:
    """
    A breaker-aware Session with NO retries, for liveness probes.

    A status answer of any kind is a pass for a probe, so there is nothing a
    second attempt could turn into one -- and session()'s status_forcelist
    would otherwise spend 9s of backoff asking a sick-but-alive host four
    times, on the one call whose entire purpose is to be cheap.
    """
    s = BreakerSession()
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=0)))
    return s


def preflight(urls, timeout=PROBE_TIMEOUT) -> list:
    """
    Touch hosts that carry several expensive calls, so the breaker learns
    about an outage in one short request rather than in one long one.

    Returns the hosts found down, read off the breaker's own record rather
    than from the exception: BreakerSession already decides what counts as a
    dead host, and deciding it twice is how two rules drift apart.

    PROBE A REAL ENDPOINT, NOT A CATALOGUE OR INDEX, and give it a budget with
    real margin. The first version of this probed the datamart's reports LIST
    endpoint on `timeout=(3, 8)`, borrowed from a page that records a healthy
    ~3.7s for it -- but ~3.7s is the TOTAL and a read timeout measures TIME TO
    FIRST BYTE. Measured when the host came back, five runs each:

        GET  the LIST endpoint       ttfb 5.17 - 6.08s    total 6.13 - 9.71s
        GET  one report slug         ttfb 3.81 - 4.96s    total 2.52 - 3.70s
        HEAD one report slug         ttfb 3.47 - 4.02s
        HEAD the LIST endpoint       ttfb 18.18 - 28.19s  and one failure

    So the shipped probe sat 1.3x clear of its own worst HEALTHY run. A
    busy-but-alive host would have tripped it and cost four figures on a day
    USDA was answering, and A PROBE THAT CRIES WOLF IS WORSE THAN NO PROBE,
    because it fails on exactly the days the page is fine.

    A report endpoint also makes a pass mean more: the catalogue is a
    different code path, so "the catalogue answered" is the weaker claim. HEAD
    is the fastest of the four and is not used -- this service handled HEAD on
    the catalogue in 18-28s and failed once in four, which is not a verb to
    put a liveness probe on.
    """
    for url in urls:
        try:
            probe_session().get(url, timeout=timeout)
        except requests.exceptions.RequestException:
            pass
    return hosts_down()
