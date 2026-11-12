"""
Nothing fetches before the letter page can paint.

Added 2026-11-12. Ross: "i've tried refreshing it and it's just spinning", on
the JSA Daily Cattle Reports page.

The Sterling margins for deck slide 7 are a live Microsoft Graph fetch, and
they sat in the Cattle Market Rundown Slide tab -- which, per the standing
rule, EXECUTES WHETHER OR NOT IT IS ON SCREEN. So every load of the page Ross
writes the letter on made a mailbox call. Graph was answering 502 that
afternoon and `sterling.fetch()` took 47s to find that out, 29s of it inside
the MSAL token refresh.

REFRESHING MADE IT WORSE, which is why it read as a hang rather than as
slowness: Streamlit serialises concurrent computation of one cache_data key
behind a lock with no timeout, so the second refresh queued behind the first
and inherited its wait.

    python -m pytest tests/test_letter_page_load.py -q
"""
import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = REPO / "apps" / "weekly_reports" / "app.py"
MAILBOX = REPO / "letter" / "mailbox.py"

# utf-8-sig: two pages in this repo carry a UTF-8 BOM and ast.parse rejects it
# as "invalid non-printable character U+FEFF", which reads as a syntax error in
# the page rather than a codec choice in the reader.
PAGE_SRC = PAGE.read_text(encoding="utf-8-sig")
PAGE_AST = ast.parse(PAGE_SRC)
MAILBOX_AST = ast.parse(MAILBOX.read_text(encoding="utf-8-sig"))


def _assign_to(tree, name):
    """Every Assign whose targets include `name`, bare or tupled."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            names = t.elts if isinstance(t, ast.Tuple) else [t]
            if any(isinstance(n, ast.Name) and n.id == name for n in names):
                out.append(node)
    return out


# -- the tabs are lazy, which is what makes `.open` mean anything ------------

def test_the_real_tabs_call_is_lazy():
    """
    `.open` is None on a tab set that was NOT given on_change="rerun", and
    None is falsy -- so the guard below would skip the Sterling fetch for
    EVER and the tab would render empty with nothing saying why. The two go
    together or neither; CLAUDE.md records that split, and the crush pages
    are the counter-example where laziness breaks a hidden sibling.
    """
    calls = [n.value for n in _assign_to(PAGE_AST, "tab_slide")
             if isinstance(n.value, ast.Call)]
    assert len(calls) == 1, "expected exactly one st.tabs binding tab_slide"
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert "on_change" in kw, "st.tabs is not lazy, so tab_slide.open is None"
    assert ast.literal_eval(kw["on_change"]) == "rerun"


def test_the_placeholder_tabs_are_left_eager():
    """
    The empty pair above `st.stop()` renders two captions and nothing else.
    Making it lazy would buy nothing and would mean a tab click rerunning a
    page that has already stopped.
    """
    calls = [n.value for n in _assign_to(PAGE_AST, "_t_slide")
             if isinstance(n.value, ast.Call)]
    assert len(calls) == 1
    assert not calls[0].keywords, "the placeholder pair does not need on_change"


# -- the fetch waits to be asked for -----------------------------------------

def test_the_sterling_fetch_is_behind_the_tab_being_open():
    """
    THE WHOLE FIX. `_sterling_data()` must be reachable only when
    `tab_slide.open` is true, so a plain page load makes no mailbox call.
    """
    assigns = _assign_to(PAGE_AST, "_st_data")
    assert len(assigns) == 1, "more than one thing assigns _st_data"
    value = assigns[0].value
    assert isinstance(value, ast.IfExp), (
        "_sterling_data() is called unconditionally -- it is back on the "
        "page-load path")

    test = value.test
    assert isinstance(test, ast.Attribute) and test.attr == "open"
    assert isinstance(test.value, ast.Name) and test.value.id == "tab_slide"
    assert isinstance(value.body, ast.Call)
    assert value.body.func.id == "_sterling_data"


def test_nothing_else_fetches_sterling():
    """
    A second call site added later would put the mailbox back on the load
    path with this test still green, so it is the call COUNT that is pinned.
    """
    calls = [n for n in ast.walk(PAGE_AST)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_sterling_data"]
    assert len(calls) == 1, f"{len(calls)} call sites for _sterling_data"

    direct = [n for n in ast.walk(PAGE_AST)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "fetch"
              and isinstance(n.func.value, ast.Name)
              and n.func.value.id == "sterling"]
    assert len(direct) == 1, "sterling.fetch() is called outside the cache"


# -- "nobody asked" must not read as "it failed" -----------------------------

def test_idle_is_not_an_error():
    """
    The branch below tests `.get("error")`. If the idle sentinel carried an
    error key, a tab nobody has opened would render "Sterling tracker
    unavailable" -- which is a false claim about Sterling and about the
    mailbox, on a page that goes on to build a client deck.
    """
    assigns = _assign_to(PAGE_AST, "_STERLING_IDLE")
    assert len(assigns) == 1
    idle = ast.literal_eval(assigns[0].value)
    assert isinstance(idle, dict)
    assert not idle.get("error"), "the idle sentinel looks like a failure"


def test_idle_is_tested_before_the_error_branch():
    """
    Order, not just presence. `_STERLING_IDLE` has no "error" key, so an
    error-first chain would fall through to the success branch and try to
    read week_ending off the sentinel.
    """
    ifs = [n for n in ast.walk(PAGE_AST)
           if isinstance(n, ast.If) and "_STERLING_IDLE" in ast.dump(n.test)]
    assert len(ifs) == 1, "the idle branch is missing"
    rest = ast.dump(ast.Module(body=ifs[0].orelse, type_ignores=[]))
    assert "'error'" in rest, "the error branch no longer follows the idle one"


# -- the one unbounded call on that page's load path -------------------------

def test_msal_is_given_a_timeout():
    """
    msal's own default is `timeout=None`, and it threads that straight into
    requests -- `functools.partial(self.http_client.request, timeout=timeout)`
    -- so the default means FOREVER. A login.microsoftonline.com that accepts
    the connection and never answers, which is exactly what USDA's datamart
    was doing that day, would hang the page with nothing to cut it off.

    Asserted on the source rather than by constructing the client, because
    that needs GRAPH_CLIENT_ID in the environment. The wiring was verified
    live when this shipped: the inner requests Session's `request` came back
    as a functools.partial carrying {'timeout': 30}.
    """
    app_fn = next(n for n in ast.walk(MAILBOX_AST)
                  if isinstance(n, ast.FunctionDef) and n.name == "_app")
    ctor = next(n for n in ast.walk(app_fn)
                if isinstance(n, ast.Call)
                and getattr(n.func, "attr", "") == "PublicClientApplication")
    kw = {k.arg for k in ctor.keywords}
    assert "timeout" in kw, "MSAL is still unbounded"


def test_the_msal_timeout_is_a_sane_band():
    """
    A band rather than a number, for the reason the host breaker's TTL
    needed one: a constant large enough to be no timeout at all would pass
    any test that merely checks the keyword is present. A silent token
    refresh answers in under a second when it is healthy.
    """
    from letter import mailbox
    assert 5 <= mailbox.MSAL_TIMEOUT <= 120, (
        f"MSAL_TIMEOUT is {mailbox.MSAL_TIMEOUT}s -- outside anything a token "
        f"refresh should ever need")


# -- the detector has to be able to fail -------------------------------------

@pytest.mark.parametrize("broken,missing", [
    ("tab_letter, tab_slide = st.tabs(TAB_LABELS)", "on_change"),
    ("_st_data = _sterling_data()", "IfExp"),
])
def test_the_guards_reject_the_broken_form(broken, missing):
    """
    A guard that cannot fail is the thing it guards against. Both of these
    are the code as it stood this morning.
    """
    tree = ast.parse(broken)
    if missing == "on_change":
        call = _assign_to(tree, "tab_slide")[0].value
        assert not call.keywords, "the broken form would have passed"
    else:
        assert not isinstance(_assign_to(tree, "_st_data")[0].value, ast.IfExp)
