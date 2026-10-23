"""
The client view — the mechanism, and the one mistake it invites.

THE MISTAKE: hiding a tab's LABEL without stopping its BODY. `portal_view.tabs`
hands back a `Hidden` stand-in for a tab the client does not get, and `Hidden`
is a no-op context manager — so `with tab_x:` still runs everything inside it,
and for a client that content renders straight into the page body with no tab
around it. The analyst tool is then not merely still there; it is there
unframed, in the middle of someone else's page, having run its fetches.

Nothing reports that. The page looks busy, which is what it looked like before.
So `test_every_hidden_tab_has_its_body_guarded` walks every `portal_view.tabs`
call in the repo, works out which name each hidden label was bound to, and
fails unless that name is tested — `if tab.open:` where the tab set is lazy, or
`portal_view.shown(tab)` where it is not.

The two guards are not interchangeable and the difference is the trap underneath
this one. A real `TabContainer.open` is None unless `on_change="rerun"` was
passed, and None is falsy, so writing `if tab.open:` on a tab set that is not
lazy skips the body on the STAFF view as well — the tab renders empty and
nobody notices until they open it. Hence the second test, which pins `.open`
guards to lazy tab sets only.

BOM: apps/beef_trimmings/app.py and apps/cattle_on_feed/app.py start with one,
and `ast.parse` rejects it as "invalid non-printable character U+FEFF" — which
reads as a syntax error in the page rather than a codec choice here. utf-8-sig,
the same fix tests/streamlit_source.py already carries.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import portal_view  # noqa: E402

APP_FILES = sorted(ROOT.glob("apps/*/app.py"))


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_src(path))


@pytest.fixture(autouse=True)
def _staff_by_default():
    """Every test starts from the staff view and leaves it there."""
    portal_view.set_client(False)
    yield
    portal_view.set_client(False)


# -- the mechanism ------------------------------------------------------------

def test_the_default_is_staff():
    """
    Absence must mean staff. Home.py is the existing deployment's main file and
    it never calls set_client, so a default of 'client' would have stripped the
    live portal the first time it rebooted after this shipped.
    """
    assert portal_view.is_staff()
    assert not portal_view.is_client()


def test_hidden_is_a_no_op_context_manager_that_skips_an_open_guard():
    h = portal_view.Hidden()
    assert h.open is False, "`if tab.open:` is what skips the body"
    ran = False
    with h:
        ran = True
    assert ran, "it must still be usable as a context manager"
    assert not portal_view.shown(h)


def test_tabs_keeps_its_arity_so_the_unpacking_never_changes(monkeypatch):
    """
    The call sites unpack a fixed number of names. If `tabs()` returned only
    the surviving tabs the client view would raise ValueError on every page
    that hides one -- and only on the client deployment.
    """
    seen = {}

    def fake_tabs(labels, **kw):
        seen["labels"] = list(labels)
        return [f"REAL:{label}" for label in labels]

    monkeypatch.setattr(portal_view.st, "tabs", fake_tabs)
    labels = ["A", "B", "C", "D"]

    portal_view.set_client(True)
    got = portal_view.tabs(labels, hide={"B", "D"})
    assert len(got) == 4
    assert got[0] == "REAL:A" and got[2] == "REAL:C"
    assert isinstance(got[1], portal_view.Hidden)
    assert isinstance(got[3], portal_view.Hidden)
    assert seen["labels"] == ["A", "C"], "hidden labels must not reach st.tabs"


def test_the_staff_view_passes_the_labels_through_untouched(monkeypatch):
    """A page's behaviour on Ross's deployment must not change at all."""
    seen = {}

    def fake_tabs(labels, **kw):
        seen["labels"] = list(labels)
        seen["kw"] = dict(kw)
        return [f"REAL:{label}" for label in labels]

    monkeypatch.setattr(portal_view.st, "tabs", fake_tabs)
    got = portal_view.tabs(["A", "B"], hide={"B"}, on_change="rerun")
    assert seen["labels"] == ["A", "B"]
    assert seen["kw"] == {"on_change": "rerun"}
    assert all(portal_view.shown(t) for t in got)


def test_hiding_a_label_that_is_not_on_the_tab_set_raises(monkeypatch):
    """
    A label renamed on the page and not in `hide` would silently stop hiding
    its tab, and the client would get the analyst tool back with nothing
    raising anywhere. Loud, because nothing downstream can report it.
    """
    monkeypatch.setattr(portal_view.st, "tabs", lambda labels, **kw: list(labels))
    portal_view.set_client(True)
    with pytest.raises(ValueError, match="not on this tab set"):
        portal_view.tabs(["Index", "Basis"], hide={"Sale Barn Basis"})


def test_hiding_every_tab_does_not_call_st_tabs(monkeypatch):
    """st.tabs([]) raises; a tab set that is entirely staff-only must not."""
    called = []
    monkeypatch.setattr(portal_view.st, "tabs",
                        lambda labels, **kw: called.append(labels) or list(labels))
    portal_view.set_client(True)
    got = portal_view.tabs(["A", "B"], hide={"A", "B"})
    assert called == []
    assert len(got) == 2 and all(isinstance(t, portal_view.Hidden) for t in got)


def test_pick_does_not_build_the_widget_for_a_client():
    """
    Streamlit draws on call, so the point of passing a callable is that it is
    never called. Passing a value would render the widget and then throw the
    result away.
    """
    built = []
    portal_view.set_client(True)
    assert portal_view.pick("Dressed", lambda: built.append(1) or "Live") == "Dressed"
    assert built == [], "the widget must not be drawn for a client"

    portal_view.set_client(False)
    assert portal_view.pick("Dressed", lambda: built.append(1) or "Live") == "Live"
    assert built == [1]


def test_staff_expander_and_staff_block_skip_the_body_entirely():
    portal_view.set_client(True)
    assert list(portal_view.staff_block()) == []
    assert list(portal_view.staff_expander("anything")) == [], \
        "a client must not even reach st.expander"


def test_options_drops_only_what_it_is_told_to():
    opts = ["Cutout", "Individual Cuts"]
    assert portal_view.options(opts, hide={"Individual Cuts"}) == opts
    portal_view.set_client(True)
    assert portal_view.options(opts, hide={"Individual Cuts"}) == ["Cutout"]


# -- the standing guard -------------------------------------------------------

def _hidden_tab_names(tree: ast.Module):
    """
    Yield (label, name, lazy) for every tab a `portal_view.tabs` call hides,
    where the labels are a literal list and the targets a tuple of names.

    `lazy` says whether that call passed on_change="rerun", which is what
    decides whether `.open` is a usable guard there.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        if not (isinstance(func, ast.Attribute) and func.attr == "tabs"
                and isinstance(func.value, ast.Name) and func.value.id == "portal_view"):
            continue

        hide = next((k.value for k in call.keywords if k.arg == "hide"), None)
        if hide is None:
            continue
        if not isinstance(hide, (ast.Set, ast.List, ast.Tuple)):
            continue
        hidden = {e.value for e in hide.elts if isinstance(e, ast.Constant)}
        if not hidden:
            continue

        if not call.args or not isinstance(call.args[0], (ast.List, ast.Tuple)):
            continue          # labels built elsewhere -- covered by its own test
        labels = [e.value for e in call.args[0].elts if isinstance(e, ast.Constant)]
        if len(labels) != len(call.args[0].elts):
            continue

        target = node.targets[0]
        if not isinstance(target, ast.Tuple):
            continue
        names = [e.id for e in target.elts if isinstance(e, ast.Name)]
        if len(names) != len(labels):
            continue

        lazy = any(k.arg == "on_change" and getattr(k.value, "value", None) == "rerun"
                   for k in call.keywords)
        for label, name in zip(labels, names):
            if label in hidden:
                yield label, name, lazy


def _guards(tree: ast.Module):
    """Names guarded by `x.open` inside an `if`, and names inside shown(x)."""
    open_guarded, shown_guarded = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            for sub in ast.walk(node.test):
                if (isinstance(sub, ast.Attribute) and sub.attr == "open"
                        and isinstance(sub.value, ast.Name)):
                    open_guarded.add(sub.value.id)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "shown"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "portal_view"):
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    shown_guarded.add(arg.id)
    return open_guarded, shown_guarded


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_every_hidden_tab_has_its_body_guarded(path):
    """
    A hidden tab whose body is not behind a check renders that body into the
    client's page, unframed, having run whatever it fetches. See this module's
    docstring.
    """
    tree = _tree(path)
    open_guarded, shown_guarded = _guards(tree)
    for label, name, lazy in _hidden_tab_names(tree):
        guarded = name in shown_guarded or (lazy and name in open_guarded)
        assert guarded, (
            f"{path.parent.name}: '{label}' is hidden from the client but "
            f"`{name}`'s body is not guarded. Use `if {name}.open:` on a tab "
            f'set that passes on_change="rerun", or '
            f"`if portal_view.shown({name}):` on one that does not."
        )


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_an_open_guard_is_only_used_on_a_lazy_tab_set(path):
    """
    `TabContainer.open` is None without on_change="rerun", and None is falsy,
    so `if tab.open:` on a non-lazy set skips the body for EVERYBODY. The page
    renders an empty tab and nothing raises.
    """
    tree = _tree(path)
    lazy_names, eager_names = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        is_tabs = (isinstance(func, ast.Attribute) and func.attr == "tabs"
                   and isinstance(func.value, ast.Name)
                   and func.value.id in ("st", "portal_view"))
        if not is_tabs:
            continue
        lazy = any(k.arg == "on_change" and getattr(k.value, "value", None) == "rerun"
                   for k in call.keywords)
        target = node.targets[0]
        names = ([e.id for e in target.elts if isinstance(e, ast.Name)]
                 if isinstance(target, ast.Tuple)
                 else [target.id] if isinstance(target, ast.Name) else [])
        (lazy_names if lazy else eager_names).update(names)

    open_guarded, _ = _guards(tree)
    stray = sorted((open_guarded & eager_names) - lazy_names)
    assert not stray, (
        f"{path.parent.name}: {stray} are guarded with `.open` but their tab "
        f'set does not pass on_change="rerun", so `.open` is None and the body '
        f"never renders -- on the staff view too."
    )


BROKEN = '''
tab_a, tab_b = portal_view.tabs(["A", "B"], hide={"B"}, on_change="rerun")
with tab_b:
    st.dataframe(raw)
'''

FIXED_LAZY = '''
tab_a, tab_b = portal_view.tabs(["A", "B"], hide={"B"}, on_change="rerun")
with tab_b:
    if tab_b.open:
        st.dataframe(raw)
'''

FIXED_EAGER = '''
tab_a, tab_b = portal_view.tabs(["A", "B"], hide={"B"})
if portal_view.shown(tab_b):
    with tab_b:
        st.dataframe(raw)
'''

WRONG_GUARD = '''
tab_a, tab_b = portal_view.tabs(["A", "B"], hide={"B"})
with tab_b:
    if tab_b.open:
        st.dataframe(raw)
'''


def _unguarded(src: str):
    tree = ast.parse(src)
    open_guarded, shown_guarded = _guards(tree)
    return [label for label, name, lazy in _hidden_tab_names(tree)
            if not (name in shown_guarded or (lazy and name in open_guarded))]


def test_the_detector_rejects_the_broken_form_and_accepts_both_fixes():
    """
    A guard test that cannot fail is the thing it guards against. These four
    are the real shapes: an unguarded body, the lazy fix, the eager fix, and
    `.open` used on a tab set that is not lazy -- which renders an empty tab on
    BOTH views and is what the second guard exists for.
    """
    assert _unguarded(BROKEN) == ["B"], "the unguarded body must be caught"
    assert _unguarded(FIXED_LAZY) == []
    assert _unguarded(FIXED_EAGER) == []
    assert _unguarded(WRONG_GUARD) == ["B"], (
        "`.open` on a non-lazy tab set is not a guard -- it is None, so the "
        "body never renders for anyone"
    )


# -- the peer comparison is staff-only ----------------------------------------

def _staff_gated_lines(tree: ast.Module) -> set[int]:
    """Lines inside an `if portal_view.is_staff():` body."""
    gated: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if (isinstance(t, ast.Call) and isinstance(t.func, ast.Attribute)
                and t.func.attr == "is_staff"
                and isinstance(t.func.value, ast.Name)
                and t.func.value.id == "portal_view"):
            for stmt in node.body:
                gated.update(range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))
    return gated


FCI_PAGE = ROOT / "apps/cme_feeder_cattle/app.py"


@pytest.mark.parametrize("needle", [
    "Versus CIH &amp; Compass",
    "Pending CME Prints &amp; Forecast Accuracy",
])
def test_the_self_scoring_sections_are_staff_only(needle):
    """
    Ross, 2026-10-23: "the clients don't need to see the versus CIH & Compass
    table", then "take out the pending cme prints section too".

    Both are JSA measuring itself -- our call against CME's print, then our
    call against the desks we compete with. The peer half is also built from
    THEIR published figures, hand-entered off their daily sheets, so putting
    it in front of a client is redistribution as well as oversharing: the line
    letter/sterling.py already draws around the Sterling tracker.
    """
    tree = ast.parse(_src(FCI_PAGE))
    gated = _staff_gated_lines(tree)
    found = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and needle in n.value]
    assert found, f"{needle!r} is not on the page at all -- did the heading change?"
    for line in found:
        assert line in gated, (
            f"{needle!r} at line {line} is not inside an "
            f"`if portal_view.is_staff():` body"
        )


def test_no_competitor_is_named_anywhere_a_client_can_see():
    """
    THE TABLE WAS NOT THE ONLY MENTION, and that is the point of this test.
    A caption two hundred lines above it read "how CME names its files and how
    CIH dates its daily sheet" -- ungated, and it would have gone on reaching
    clients after the table came out. Removing the thing that was pointed at
    is not the same as removing the exposure.

    Docstrings are excluded: they are for whoever reads this file.
    """
    tree = ast.parse(_src(FCI_PAGE))
    gated = _staff_gated_lines(tree)

    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node, clean=False):
                first = node.body[0]
                docstring_lines.update(
                    range(first.lineno, (first.end_lineno or first.lineno) + 1))

    leaks = [(n.lineno, n.value[:60]) for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and ("CIH" in n.value or "Compass" in n.value)
             and n.lineno not in gated and n.lineno not in docstring_lines]
    assert not leaks, f"competitor named outside a staff gate: {leaks}"


def test_the_peer_table_and_the_scorecard_share_one_gate():
    """
    `_recon` and `_openings` are loaded by the scorecard and read by the peer
    table. Gating them separately would leave the table raising NameError the
    moment somebody un-gated it on its own -- so they must sit under the SAME
    `if`, not under two.
    """
    tree = ast.parse(_src(FCI_PAGE))
    for name in ("_recon", "_openings"):
        assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == name
                           for t in n.targets)]
        reads = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Name) and n.id == name
                 and isinstance(n.ctx, ast.Load)]
        assert assigns and reads, f"{name} should be both written and read"
        gated = _staff_gated_lines(tree)
        for n in assigns:
            assert n.lineno in gated, f"{name} is assigned outside the staff gate"
        for line in reads:
            assert line in gated, (
                f"{name} is read at line {line}, outside the staff gate that "
                f"defines it -- a client would get NameError"
            )


# -- the client portal's passphrase gate --------------------------------------

def _home_tree() -> ast.Module:
    return ast.parse((ROOT / "Home.py").read_text(encoding="utf-8"))


def _call_line(tree, attr, owner=None):
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr):
            if owner is None or (isinstance(n.func.value, ast.Name)
                                 and n.func.value.id == owner):
                return n.lineno
    return None


def test_the_gate_sits_above_st_navigation():
    """
    Streamlit executes Home.py on EVERY request, including a deep link straight
    to /beef-cutout, and then dispatches. A gate below st.navigation leaves
    every deep link open while the home page looks locked -- which is worse
    than no gate, because it looks like one.
    """
    tree = _home_tree()
    cfg = _call_line(tree, "set_page_config", "st")
    gate = _call_line(tree, "require_passphrase", "portal_auth")
    nav = _call_line(tree, "navigation", "st")
    assert gate, "Home.py no longer calls portal_auth.require_passphrase"
    assert cfg < gate, "the gate must follow set_page_config, the run's first st call"
    assert gate < nav, "the gate must precede st.navigation or deep links bypass it"


def test_the_gate_is_client_only():
    """
    Ross's own app is opened many times a day and is not the URL handed out.
    Gating it would put a box in front of the letter every morning for nothing.
    """
    tree = _home_tree()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if _call_line(node, "require_passphrase", "portal_auth") is None:
            continue
        t = node.test
        assert (isinstance(t, ast.Call) and isinstance(t.func, ast.Attribute)
                and t.func.attr == "is_client"
                and isinstance(t.func.value, ast.Name)
                and t.func.value.id == "portal_view"), (
            "the gate must be behind `if portal_view.is_client():`"
        )
        return
    raise AssertionError("require_passphrase is not inside an `if` at all")


def test_no_passphrase_is_assigned_as_a_literal_anywhere():
    """
    THIS REPO IS PUBLIC. A passphrase committed here is a passphrase
    published, and two API keys were already removed from it in September for
    exactly that.

    THIS TEST DELIBERATELY DOES NOT CONTAIN THE PASSPHRASE. The first version
    searched for the literal value, which meant writing that value into this
    file -- leaking it into the public repo in the course of testing that it
    is not in the public repo. Pattern, not value: nothing may ASSIGN a
    passphrase, and the gate may never compare against a hard-coded string.
    """
    import re
    skip = {".git", "__pycache__", ".venv", "out", "node_modules", "assets"}
    assign = re.compile(
        r"""\b([A-Z_]*PASSPHRASE|[A-Z_]*PASSWORD)\s*=\s*["'][^"']+["']""")
    bad = []
    for path in ROOT.rglob("*.py"):
        if set(path.parts) & skip:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for m in assign.finditer(text):
            line = text[:m.start()].count(chr(10)) + 1
            bad.append(f"{path.relative_to(ROOT)}:{line} "
                       f"assigns {m.group(1)} to a literal")
    assert not bad, "; ".join(bad)


def test_the_gate_compares_against_the_configured_secret_only():
    """
    portal_auth must get the value from secrets or the environment, never from
    a constant in the file. If a literal ever creeps into the comparison this
    catches it without anyone having to know what the literal is.
    """
    tree = ast.parse((ROOT / "portal_auth.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "require_passphrase")
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "compare_digest"):
            for arg in node.args:
                assert not isinstance(arg, ast.Constant), (
                    "the gate compares against a hard-coded string")
            return
    raise AssertionError("require_passphrase no longer uses hmac.compare_digest")


def test_the_gate_fails_closed(monkeypatch):
    """
    With no secret configured nobody gets in and the page says why. A gate that
    turns itself off when misconfigured is not a gate -- and this is the whole
    reason the secret has to be set BEFORE the code ships.
    """
    import portal_auth
    monkeypatch.setattr(portal_auth, "configured_passphrase", lambda *a, **k: "")
    calls = {"stopped": False, "shell": None}
    monkeypatch.setattr(portal_auth, "_shell",
                        lambda title, body: calls.__setitem__("shell", (title, body)))

    class _Stop(Exception):
        pass

    def _stop():
        calls["stopped"] = True
        raise _Stop

    monkeypatch.setattr(portal_auth.st, "stop", _stop)
    monkeypatch.setattr(portal_auth.st, "session_state", {})
    with pytest.raises(_Stop):
        portal_auth.require_passphrase("PORTAL_PASSPHRASE")
    assert calls["stopped"]
    assert "not configured" in calls["shell"][0]


# -- the two entry points -----------------------------------------------------

def test_client_py_sets_the_view_before_it_runs_the_shell():
    """
    Home.py imports pages at module scope. set_client() landing after the shell
    had started would leave the first render in the staff view.
    """
    tree = ast.parse((ROOT / "Client.py").read_text(encoding="utf-8"))
    lines = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            lines.setdefault(node.func.attr, node.lineno)
    assert "set_client" in lines and "run_path" in lines
    # Line numbers off the AST, not string positions: this module's own
    # docstring names runpy.run_path several paragraphs above the code.
    assert lines["set_client"] < lines["run_path"]


def test_client_py_holds_no_layout_of_its_own():
    """
    One copy of the grid. A second DASHBOARDS list here is how the client
    landing page quietly stops matching the staff one -- the failure this repo
    records for snowflake_db.py five times over.
    """
    src = (ROOT / "Client.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]          # past the docstring
    for forbidden in ("DASHBOARDS", "TOOLS", "_TILE_CSS", "st.columns", "st.Page"):
        assert forbidden not in body, f"Client.py must not carry {forbidden}"


def test_client_py_does_not_import_home():
    """
    Streamlit re-executes the main script every rerun. `import Home` is a
    cached no-op from the second rerun on, so the portal would render once and
    then come up blank -- which looks like a crashed app, not a wiring choice.
    """
    src = (ROOT / "Client.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]
    assert "import Home" not in body
    assert "runpy.run_path" in body


def test_portal_view_exists_exactly_once():
    """Python caches by NAME. A second copy beside a page would mean whichever
    page loaded first decided which view every other page got."""
    assert [p.relative_to(ROOT) for p in ROOT.rglob("portal_view.py")
            if "__pycache__" not in p.parts] == [Path("portal_view.py")]


def test_the_client_home_has_no_staff_door():
    """
    Ross asked for this directly. The client deployment carries no admin
    passphrase, so admin_sign_in() could only ever render a form that fails --
    and ?tools=1 would otherwise register three tiles whose pages answer "not
    configured", telling a client the tools exist and are broken in one click.
    """
    home = (ROOT / "Home.py").read_text(encoding="utf-8")
    assert "portal_view.staff_only(portal_auth.admin_sign_in)" in home
    assert "st.write(\"\")\n    portal_auth.admin_sign_in()" not in home

    tools_fn = home[home.index("def tools_visible("):home.index("def render_home(")]
    assert "if portal_view.is_client():\n        return False" in tools_fn, \
        "?tools=1 must be dead on the client deployment"
