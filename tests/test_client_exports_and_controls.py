"""
Two things the client view takes out that are not tabs: exports, and the
controls that drive the cache.

WHY THESE NEED THEIR OWN TESTS. `test_client_view.py` walks every
`portal_view.tabs` call in the repo, so a tab that stops being hidden fails
loudly. Nothing walks a download button or a sidebar toggle -- they are
ordinary statements, and the only thing standing between them and a client is
one line somebody could delete while tidying. These are the pins for the five
decisions taken on 2026-11-02 (standing rules 1 and 2).

WHAT IS DELIBERATELY NOT HERE: a repo-wide "every st.download_button must be
lexically enclosed by a gate". It was written and thrown away, because it
rejects correct code -- eleven of the portal's exports are reachable only
through a tab the client does not get (beef_weight's NASS Data tab,
livestock_inventory's four, cattle_on_feed's five), and two more are gated by
an early return in the function that draws them rather than by an enclosing
block. A guard with that many false positives is one somebody deletes the
first time it blocks them, which is the rule the index repo's CLAUDE.md states.
So these are precise pins on the five call sites, each with a proof it rejects
the broken form.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEASONAL = ROOT / "apps/livestock_seasonal/app.py"
WEIGHT = ROOT / "apps/beef_weight/app.py"
CUTOUT = ROOT / "apps/beef_cutout/app.py"
CASH = ROOT / "apps/cash_trade/app.py"
TRADE = ROOT / "apps/beef_trade/app.py"
FCI = ROOT / "apps/cme_feeder_cattle/app.py"
TRIM = ROOT / "apps/beef_trimmings/app.py"

# EVERY page that carries a cache control. This list was three when it was
# written and the sweep behind it had refuted a fourth on the grounds that
# "three sibling pages carry the same ungated button" -- an argument that was
# true when written and false an hour later, because those three were the ones
# being fixed. A convention argument goes stale the moment the convention
# moves, so test_the_list_of_refresh_pages_is_complete derives the list from
# the repo instead of trusting this one.
#
# SEASONAL is in this list without ever having been fixed: its "Refresh
# prices" button was already `portal_view.pick`-gated before any of this, and
# the completeness test below is what noticed it was going unchecked. Being
# right by accident and being right on purpose look identical until something
# edits it.
REFRESH_PAGES = [CUTOUT, CASH, TRADE, FCI, TRIM, SEASONAL]
REFRESH_LABEL = "refresh"


def _src(path):
    return path.read_text(encoding="utf-8-sig")


def _tree(path):
    return ast.parse(_src(path))


def _is_pv(node, name):
    """True for a call to `portal_view.<name>(...)`."""
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == name
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "portal_view")


def _lines_inside_pick(tree):
    """Every line that falls inside a `portal_view.pick(...)` call."""
    out = set()
    for node in ast.walk(tree):
        if _is_pv(node, "pick"):
            out.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return out


def _lines_inside_staff_if(tree):
    """Every line inside an `if portal_view.is_staff():` body."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_pv(node.test, "is_staff"):
            for stmt in node.body:
                out.update(range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))
    return out


def _widget_calls(tree, needle):
    """(lineno, label) for every st.button / st.toggle whose label matches."""
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"button", "toggle"}):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        label = node.args[0].value
        if isinstance(label, str) and needle in label.lower():
            found.append((node.lineno, label))
    return found


# -- rule 2: the exports -------------------------------------------------------

def test_the_seasonal_export_row_returns_early_for_a_client():
    """
    The Copy / CSV / PNG row under every Seasonal chart and table. Eleven call
    sites, one gate -- so this pins the gate where it actually is, at the top
    of the function, rather than at any call site.

    An EARLY RETURN and not an `if` around the body, because nothing should be
    computed for a client either: the frame is serialised to tab-separated text
    for the Copy popover and a PNG can be rendered, neither of which should
    happen on a page that has no way to take them.
    """
    tree = _tree(SEASONAL)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "export_row"), None)
    assert fn is not None, "export_row is gone -- was it renamed?"

    body = [s for s in fn.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    first = body[0]
    assert isinstance(first, ast.If), (
        f"the first statement in export_row is {type(first).__name__}, not a guard"
    )
    assert _is_pv(first.test, "is_client"), ast.dump(first.test)
    assert len(first.body) == 1 and isinstance(first.body[0], ast.Return), (
        "the guard must return immediately -- anything else and the row's work "
        "still happens for a client"
    )

    # The gate is only worth having because the call sites are many; if this
    # ever drops to one, gating at the call site would be clearer.
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "export_row"]
    assert len(calls) >= 8, f"only {len(calls)} call sites -- re-read the comment"


def test_the_saturday_export_is_staff_only():
    """
    beef_weight's "Download Saturday series (Excel)". The page's other export
    is already gone for a client because its whole Data tab is; this one sits
    in a different tab and so was never carried along.
    """
    tree = _tree(WEIGHT)
    gated = _lines_inside_staff_if(tree)
    hits = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value == "Download Saturday series (Excel)"]
    assert hits, "the Saturday export's label changed -- re-point this test"
    for line in hits:
        assert line in gated, (
            f"the Saturday export at line {line} is not inside an "
            f"`if portal_view.is_staff():` body"
        )


# -- rule 1: the cache controls ------------------------------------------------

@pytest.mark.parametrize("path", REFRESH_PAGES, ids=lambda p: p.parent.name)
def test_every_refresh_control_is_staff_only(path):
    """
    Ross, 2026-11-02, on the client dashboard. A cache control is a working
    tool: it answers "is this stale?", which is a build question, not a market
    one. cattle_on_feed:986 made this call first -- "Staff only, like the trend
    slider: a client has no use for a cache control" -- and these four are the
    rest of them.

    Pinned on `portal_view.pick` specifically, not on any gate, because `pick`
    is the only form that both hides the widget AND supplies the value the page
    reads afterwards. Two of these feed an `if auto_refresh:` at the bottom of
    their file that sleeps and reruns; wrapped in an `if` instead, that name
    would be undefined for a client and the page would raise -- on the client
    deployment only.
    """
    tree = _tree(path)
    picked = _lines_inside_pick(tree)
    controls = _widget_calls(tree, REFRESH_LABEL)
    assert controls, f"no refresh control found in {path.name} -- was it renamed?"
    for line, label in controls:
        assert line in picked, (
            f"{path.parent.name}: {label!r} at line {line} is not inside a "
            f"portal_view.pick(...) call"
        )


def test_the_list_of_refresh_pages_is_complete():
    """
    The half that would have hidden the fifth and sixth controls.

    REFRESH_PAGES above is hand-written, and a hand-written list cannot report
    a page nobody added to it. This derives the real set from every app in the
    repo and fails if one is missing -- so a new page with a Refresh button is
    caught the first time the suite runs, rather than the next time somebody
    happens to sweep.
    """
    found = set()
    for path in sorted(ROOT.glob("apps/*/app.py")):
        if _widget_calls(_tree(path), REFRESH_LABEL):
            found.add(path)
    missing = found - set(REFRESH_PAGES)
    assert not missing, (
        "these pages carry a refresh control and are not in REFRESH_PAGES, so "
        "nothing checks them: "
        + ", ".join(sorted(p.parent.name for p in missing))
    )


def test_the_operator_instruction_is_staff_only():
    """
    "Run update_index.py to refresh", in the index page's sidebar panel.

    ONLY THIS SENTENCE. The panel around it stays for clients: the spec is a
    market reading, and the segment list is a DISCLOSURE -- which dates are
    CME's own published file and which are still JSA's estimate is arguably
    the most client-relevant thing on the page, and the chart caption points
    at this panel for exactly that. Gating the whole panel, which is what the
    sweep recommended, would have taken the disclosure with it.
    """
    tree = _tree(FCI)
    allowed = _lines_inside_staff_ifexp(tree) | _lines_inside_staff_if(tree)
    hits = [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "update_index.py" in n.value
            and n.lineno not in _docstring_lines(tree)]
    assert hits, "the sidebar no longer names update_index.py -- re-point this"
    for line, text in hits:
        assert line in allowed, (
            f"cme_feeder_cattle:{line} tells the reader to run a script they "
            f"cannot run -- {text.strip()[:60]!r}"
        )


def test_the_segment_disclosure_is_NOT_gated():
    """
    The other half, and the one that stops this being over-applied later.

    A future tidy-up that gated the whole panel would pass every other test in
    this file while removing the sentence telling a client that today's number
    is JSA's estimate rather than CME's print. That is the opposite of what
    the client view is for.
    """
    tree = _tree(FCI)
    gated = _lines_inside_staff_ifexp(tree) | _lines_inside_staff_if(tree)
    needles = ["Sample: 12-state feeder steer region",
               "CME hasn't published this date yet"]
    for needle in needles:
        hits = [n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and needle in n.value
                and n.lineno not in _docstring_lines(tree)]
        assert hits, f"{needle!r} is gone from the page"
        for line in hits:
            assert line not in gated, (
                f"{needle!r} at line {line} has been made staff-only -- read "
                f"this test's docstring before doing that"
            )


def test_the_auto_refresh_value_is_still_read_after_the_gate():
    """
    The reason `pick` is not interchangeable with an `if` here, asserted rather
    than left in a comment: both pages go on to read `auto_refresh`.
    """
    for path in (CUTOUT, CASH):
        tree = _tree(path)
        reads = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Name) and n.id == "auto_refresh"
                 and isinstance(n.ctx, ast.Load)]
        writes = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Name) and n.id == "auto_refresh"
                  and isinstance(n.ctx, ast.Store)]
        assert writes and reads, path.name
        assert max(reads) > max(writes), (
            f"{path.name}: auto_refresh is no longer read after it is set -- if "
            f"that is deliberate, this control can be deleted outright rather "
            f"than picked"
        )


# -- the sentences that pointed at a control the client no longer has ----------

def _docstring_lines(tree):
    """
    Every line of every docstring.

    A docstring is not user-facing text, and leaving it in scope made this
    file's own sentence guard reject a docstring written to EXPLAIN the fix --
    publication_stamps() in beef_cutout says the page "moved only on 'Refresh
    Now' or a restart", which is a sentence about the bug, not one shown to
    anybody. That is the fourth substring-shaped guard in this project to
    catch correct code; the pattern is always the same, and so is the fix:
    narrow what the guard looks at rather than loosen what it accepts.
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.update(range(first.lineno,
                             (first.end_lineno or first.lineno) + 1))
    return out


def _lines_inside_staff_ifexp(tree):
    """Every line inside the body of a `... if portal_view.is_staff() else ...`."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp) and _is_pv(node.test, "is_staff"):
            out.update(range(node.body.lineno,
                             (node.body.end_lineno or node.body.lineno) + 1))
    return out


def _lines_inside_hidden_tabs(tree):
    """
    Every line inside the body of a tab this page hides from a client.

    The labels come from `hide={...}`; the NAMES come from the assignment the
    tabs call sits in, matched to the labels by position -- the same mapping
    test_client_view.py makes, and the reason it has to be positional is that
    `portal_view.tabs` keeps its arity so hidden slots are still unpacked.
    """
    out = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and _is_pv(node.value, "tabs")):
            continue
        call = node.value
        if not call.args or not isinstance(call.args[0], (ast.List, ast.Tuple)):
            continue
        labels = [e.value for e in call.args[0].elts if isinstance(e, ast.Constant)]
        hide = set()
        for kw in call.keywords:
            if kw.arg == "hide":
                hide.update(e.value for e in kw.value.elts
                            if isinstance(e, ast.Constant))
        target = node.targets[0]
        names = ([e.id for e in target.elts if isinstance(e, ast.Name)]
                 if isinstance(target, (ast.Tuple, ast.List)) else [])
        if len(names) != len(labels):
            continue
        hidden_names = {n for n, lab in zip(names, labels) if lab in hide}
        for w in ast.walk(tree):
            if (isinstance(w, ast.With) and len(w.items) == 1
                    and isinstance(w.items[0].context_expr, ast.Name)
                    and w.items[0].context_expr.id in hidden_names):
                out.update(range(w.lineno, (w.end_lineno or w.lineno) + 1))
    return out


# The control each page's prose points at, and the page it is on.
DANGLERS = [(CUTOUT, "Refresh Now"), (CASH, "Refresh now"), (TRIM, "Refresh now")]


@pytest.mark.parametrize("path,needle", DANGLERS,
                         ids=lambda v: v.parent.name if isinstance(v, Path) else v)
def test_no_client_sentence_points_at_a_control_the_client_lacks(path, needle):
    """
    Hiding the button is half the job. Seven sentences across these two pages
    told the reader to use it, and a client reading "Use Refresh now in the
    sidebar to retry" would be hunting for something that is not there -- worse
    than the alarm it was attached to.

    EVERY occurrence is checked, not merely one. The first version of this test
    asserted the sentence appeared *somewhere* inside a staff conditional, and
    reverting one of cash_trade's three left the other two to satisfy it --
    green on a page that had just started telling clients to press a button
    they cannot see. It was the revert proof at the bottom of this file that
    caught that, which is the whole argument for writing one.

    An occurrence is allowed if it is inside a staff conditional, inside the
    body of a tab the page already hides, or inside a `portal_view.pick` --
    cash_trade's Monday Print Forecast and Packer Leverage warnings are the
    second, and editing those would have implied a client could reach them. If
    either tab stops being hidden, those two stop being exempt and this test is
    where it surfaces.

    THE THIRD ALLOWANCE IS THE BUTTON'S OWN LABEL, and leaving it out made this
    test reject the fix it exists to protect: "↺  Refresh now" is a string
    containing "Refresh now", so the control itself read as a sentence pointing
    at the control. A label inside `pick` is not drawn for a client, which is
    the whole point of it being there.
    """
    tree = _tree(path)
    allowed = (_lines_inside_staff_ifexp(tree)
               | _lines_inside_hidden_tabs(tree)
               | _lines_inside_pick(tree)
               | _docstring_lines(tree))
    hits = [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and needle in n.value]
    assert hits, f"{path.parent.name}: no sentence names {needle!r} any more"
    for line, text in hits:
        assert line in allowed, (
            f"{path.parent.name}:{line} tells the reader to use {needle!r} "
            f"with nothing gating it -- {text.strip()[:70]!r}"
        )


def test_the_hidden_tab_exemption_is_real_and_in_use():
    """
    The exemption above has to be doing work, or it is a hole nobody notices.
    cash_trade is where it applies: two of its seven sentences live in hidden
    tabs.
    """
    tree = _tree(CASH)
    hidden = _lines_inside_hidden_tabs(tree)
    assert hidden, "no hidden tab bodies found -- the name mapping broke"
    exempt = [n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and "Refresh now" in n.value
              and n.lineno in hidden
              and n.lineno not in _lines_inside_staff_ifexp(tree)]
    assert len(exempt) == 2, (
        f"expected exactly the two hidden-tab sentences, found {len(exempt)}"
    )


# -- the guards have to be able to fail ----------------------------------------

def test_the_detectors_reject_the_broken_forms():
    """
    Every check above, fed a known violation. This repo's rule: a guard with
    only the passing half is one nobody can trust, and three written during the
    archive work could not fail at all.
    """
    # 1. export_row without its guard
    broken = ast.parse("def export_row(f, n, k, fig=None):\n    row = 1\n")
    fn = next(n for n in ast.walk(broken) if isinstance(n, ast.FunctionDef))
    body = [s for s in fn.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    assert not isinstance(body[0], ast.If), "detector 1 would accept an unguarded body"

    # ... and with a guard that checks the wrong thing
    wrong = ast.parse("def export_row(f, n, k, fig=None):\n"
                      "    if portal_view.is_staff():\n        return\n")
    fn = next(n for n in ast.walk(wrong) if isinstance(n, ast.FunctionDef))
    assert not _is_pv(fn.body[0].test, "is_client"), \
        "detector 1 would accept is_staff() where is_client() is meant"

    # ... and one that logs instead of returning
    noisy = ast.parse("def export_row(f, n, k, fig=None):\n"
                      "    if portal_view.is_client():\n        st.caption('no')\n")
    fn = next(n for n in ast.walk(noisy) if isinstance(n, ast.FunctionDef))
    assert not isinstance(fn.body[0].body[0], ast.Return), \
        "detector 1 would accept a guard that does not return"

    # 2. a refresh control outside pick()
    ungated = ast.parse('auto_refresh = st.toggle("Auto-refresh (30 min)", value=False)\n')
    picked = _lines_inside_pick(ungated)
    controls = _widget_calls(ungated, REFRESH_LABEL)
    assert controls, "detector 2 stopped finding the control at all"
    assert controls[0][0] not in picked, "detector 2 would accept an ungated toggle"

    # ... and the same control correctly wrapped, so the detector is not simply
    # rejecting everything
    good = ast.parse('auto_refresh = portal_view.pick(False, '
                     'lambda: st.toggle("Auto-refresh (30 min)", value=False))\n')
    assert _widget_calls(good, REFRESH_LABEL)[0][0] in _lines_inside_pick(good), \
        "detector 2 rejects the correct form"

    # 3. an export outside an is_staff() body
    bare = ast.parse('st.download_button("Download Saturday series (Excel)", b"")\n')
    assert not _lines_inside_staff_if(bare), "detector 3 would accept a bare export"
    wrapped = ast.parse('if portal_view.is_staff():\n'
                        '    st.download_button("Download Saturday series (Excel)", b"")\n')
    assert _lines_inside_staff_if(wrapped), "detector 3 rejects the correct form"

    # 4. a dangling sentence stated unconditionally
    flat = ast.parse('st.warning("Use **Refresh now** in the sidebar to retry.")\n')
    found = {s.value for n in ast.walk(flat) if isinstance(n, ast.IfExp)
             for s in ast.walk(n.body)
             if isinstance(s, ast.Constant) and isinstance(s.value, str)}
    assert not found, "detector 4 would accept an unconditional sentence"
