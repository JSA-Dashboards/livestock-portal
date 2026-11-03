"""
Which change the futures figures quote, and the one place that decides it.

Ross, 2026-11-03, writing Monday's full format on a Tuesday having not sent
Monday's: "it shows the prices through the close on 11/3 as just today's move
- not the weekly closes so far."

The gap was not cosmetic that evening. Live cattle were -1.55 on the session
and -2.80 on the week; feeders were -3.90 and -3.25. Feeders had rallied
Monday and broken Tuesday, so the session figure OVERSTATED their week while
the live cattle one understated theirs -- opposite directions, one letter.
"""
import ast
import pathlib

import pytest

from letter import build, config, render

REPO = pathlib.Path(__file__).resolve().parents[1]


# -- the resolver -------------------------------------------------------------

@pytest.mark.parametrize("kind,expected", [
    ("tuesday", "day"),
    ("recap", "day"),
    ("friday", "week"),
    ("am", "day"),
])
def test_the_format_decides_when_nothing_is_chosen(kind, expected):
    """Nobody's letter moves until they pick. The default is the format's."""
    ctx = {"kind": kind}
    assert build.select_change_basis(ctx, kind) == expected
    assert ctx["change_basis"] == expected
    assert ctx["change_basis_choice"] == ""


@pytest.mark.parametrize("kind", ["tuesday", "recap", "friday", "am"])
@pytest.mark.parametrize("choice", ["day", "week"])
def test_a_choice_overrides_the_format(kind, choice):
    ctx = {"kind": kind, "change_basis_choice": choice}
    assert build.select_change_basis(ctx, kind) == choice


@pytest.mark.parametrize("junk", ["", None, "weekly", "WEEK ", "session", 0])
def test_an_unusable_choice_falls_back_to_the_format(junk):
    """
    A stored value that is not one of the two bases must not reach the letter.

    `"WEEK "` is in here on purpose: the resolver strips and lowercases, so
    that one IS honoured as "week" -- the parametrisation asserts the
    normalised form rather than rejecting it, which is the behaviour a value
    hand-edited into the ctx file should get.
    """
    ctx = {"kind": "tuesday", "change_basis_choice": junk}
    got = build.select_change_basis(ctx, "tuesday")
    expected = "week" if str(junk).strip().lower() == "week" else "day"
    assert got == expected


def test_the_live_kind_beats_the_cached_one():
    """
    THE FORMAT RADIO MOVES WITHOUT THE CACHED ctx FOLLOWING IT.

    ctx["kind"] is whatever was fetched. The page hands the resolver the
    live `kind`, so switching the radio re-bases the column on that rerun
    rather than one late.
    """
    ctx = {"kind": "friday"}
    assert build.select_change_basis(ctx, "tuesday") == "day"
    assert build.select_change_basis(ctx, "friday") == "week"
    # ...and with nothing passed it does fall back to the ctx's own kind.
    assert build.select_change_basis({"kind": "friday"}) == "week"


def test_a_pre_2026_09_24_cache_cannot_impose_week_over_week():
    """
    THE REASON THE OVERRIDE IS A SEPARATE KEY.

    Every data_<slug>_<date>.json ever written stores a `change_basis`, and
    the ones from before 2026-09-24 store "week" for every format -- which is
    why main() used to discard the cached value and re-derive from the format.
    Reading that old key as an override would resurrect the bug on every
    historical letter: a Monday quoting week over week, and printing [[?]]
    for it. `change_basis_choice` is absent from all of them.
    """
    cached = {"kind": "tuesday", "change_basis": "week"}
    assert build.select_change_basis(cached, "tuesday") == "day"
    assert cached["change_basis"] == "day"


# -- the draft and the letter cannot quote different moves --------------------

def _ctx_with(basis_choice):
    ctx = {
        "kind": "tuesday",
        "change_basis_choice": basis_choice,
        "live_cattle": [{"month": "Dec", "settle": 218.15,
                         "change_day": -1.55, "change_week": -2.80}],
        "feeder_cattle": [{"month": "Nov", "settle": 334.525,
                           "change_day": -3.90, "change_week": -3.25}],
        "tech_lc": None, "tech_fc": None,
        "cash": {}, "cutout": {}, "slaughter": {}, "daily_slaughter": {},
        "carcass_weights": {}, "fci": {}, "douglas": {}, "cftc": {},
        "regional_cash": {}, "cof": {}, "outside": [], "chart": {},
        "calendar": [],
    }
    build.select_change_basis(ctx, "tuesday")
    return ctx


@pytest.mark.parametrize("choice,lc,fc", [
    ("", "-1.55", "-3.9"),       # the format's own: the session
    ("week", "-2.8", "-3.25"),   # the override Ross asked for
])
def test_the_draft_and_the_letter_quote_the_same_move(choice, lc, fc):
    """
    ONE NUMBER, TWO SURFACES. `hints()` writes the figure block Ross writes
    against; `render.futures_block` prints into the letter. Both read
    ctx["change_basis"], and this is the pairing that goes wrong when two
    callers resolve it separately.
    """
    ctx = _ctx_with(choice)
    drafted = "\n".join(sum(build.hints(ctx, "tuesday").values(), []))
    letter = (render.futures_block("Live Cattle", ctx["live_cattle"], ctx["change_basis"])
              + render.futures_block("Feeder Cattle", ctx["feeder_cattle"],
                                     ctx["change_basis"]))
    for want in (lc, fc):
        assert want in drafted, f"{want} missing from the draft figures"
        assert want in letter, f"{want} missing from the rendered letter"

    # ...and the move it is NOT quoting appears in neither.
    unused = ("-2.8", "-3.25") if choice != "week" else ("-1.55", "-3.9")
    for gone in unused:
        assert gone not in drafted
        assert gone not in letter


def test_the_draft_labels_which_move_it_is_quoting():
    """
    The letter prints no label at all -- render.futures_block renders
    "Dec: -2.80 at 218.15" and nothing says which move that is. The DRAFT
    does, and that label has to follow the same switch as the number or it
    tells Ross the wrong thing about the figure beside it.
    """
    assert "(week to date)" in "\n".join(
        sum(build.hints(_ctx_with("week"), "tuesday").values(), []))
    assert "(session)" in "\n".join(
        sum(build.hints(_ctx_with(""), "tuesday").values(), []))


# -- the ordering guard -------------------------------------------------------
#
# PER SCOPE, NOT PER FILE, AND THE FIRST VERSION WAS PER FILE. letter/build.py
# resolves the basis in TWO places -- gather() near the top and main() near the
# bottom -- so "the earliest resolver precedes the earliest hints()" was
# satisfied by gather() no matter where main()'s call sat. Checked by putting
# main()'s resolution back after hints(), the exact bug being guarded: the
# suite stayed green. A guard that cannot fail is the thing it guards against.


def _calls(path):
    """{scope name: {called function: [line, ...]}} for one module."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def scope_of(lineno):
        # Innermost function whose body spans this line; "<module>" for the
        # top-level script code an authoring page is made of.
        best, best_span = "<module>", None
        for f in funcs:
            if f.lineno <= lineno <= (f.end_lineno or f.lineno):
                span = (f.end_lineno or f.lineno) - f.lineno
                if best_span is None or span < best_span:
                    best, best_span = f.name, span
        return best

    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name in ("hints", "select_change_basis"):
            out.setdefault(scope_of(node.lineno), {}).setdefault(name, []).append(node.lineno)
    return out


@pytest.mark.parametrize("rel", ["letter/build.py", "apps/weekly_reports/app.py"])
def test_the_basis_is_resolved_before_hints_reads_it(rel):
    """
    IT USED TO BE RESOLVED AFTER, in build.main -- nine lines after the
    write_template() call that passes hints(ctx, kind).

    hints() reads ctx["change_basis"] for both the number it quotes and the
    "(session)" / "(week to date)" it labels it with. On the --no-fetch path,
    the run that makes the emailed PDF, ctx comes off disk -- so a file
    carrying the pre-2026-09-24 "week" gave Ross a draft quoting the weekly
    move while the letter beside it rendered the session's. Both honestly
    computed, neither raising.

    Latent rather than reported, because the files that trigger it are old
    ones. The override would have made it an everyday occurrence, which is
    why it is fixed here rather than noted.
    """
    scopes = _calls(REPO / rel)
    checked = 0
    for scope, calls in scopes.items():
        if "hints" not in calls:
            continue
        checked += 1
        resolved = calls.get("select_change_basis")
        assert resolved, (f"{rel}:{scope} calls hints() and never resolves "
                          "the basis")
        assert min(resolved) < min(calls["hints"]), (
            f"{rel}:{scope}: select_change_basis at {min(resolved)} runs "
            f"AFTER hints() at {min(calls['hints'])}")
    assert checked, f"{rel} no longer calls hints() -- re-point this test"


def test_the_ordering_guard_is_scoped_and_reads_code_not_comments():
    """
    Two ways this check could pass while the code is broken, both met once.

    A sibling scope satisfying it -- gather() covering for main() -- and a
    COMMENT satisfying it: the block added to app.py explains the hazard in
    prose containing "hints(ctx, kind)". Parsing to an AST handles the
    second for free; the per-scope grouping is what handles the first.
    """
    import tempfile

    good = ("def main():\n"
            "    select_change_basis(ctx, kind)\n"
            "    write(hints(ctx, kind))\n")
    # gather() resolves; main() does not until after hints(). The old
    # per-file check passed this.
    bad = ("def gather():\n"
           "    select_change_basis(ctx, kind)\n"
           "def main():\n"
           "    write(hints(ctx, kind))\n"
           "    select_change_basis(ctx, kind)\n")
    commented = ("def main():\n"
                 "    # resolve before hints(ctx, kind) or the draft disagrees\n"
                 "    select_change_basis(ctx, kind)\n"
                 "    write(hints(ctx, kind))\n")

    def scopes_for(src):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(src)
        return _calls(pathlib.Path(fh.name))

    ok = scopes_for(good)["main"]
    assert min(ok["select_change_basis"]) < min(ok["hints"])

    broken = scopes_for(bad)["main"]
    assert min(broken["select_change_basis"]) > min(broken["hints"]), (
        "the detector must see main() resolving too late even though "
        "gather() resolves early")

    cmt = scopes_for(commented)["main"]
    assert len(cmt["hints"]) == 1, "a comment was counted as a call"
    assert min(cmt["select_change_basis"]) < min(cmt["hints"])


def test_nothing_derives_the_basis_outside_the_one_resolver():
    """
    `config.change_basis_for` is the format lookup. Calling it anywhere but
    inside select_change_basis is a second place deciding the basis, which
    is how the draft and the letter came to disagree in the first place.
    `change_basis_label` is exempt: it is a caption, not a decision.
    """
    tree = ast.parse((REPO / "letter/build.py").read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "change_basis_for"
                    and node.name != "select_change_basis"):
                offenders.append(node.name)
    assert not offenders, f"these derive the basis themselves: {sorted(set(offenders))}"
