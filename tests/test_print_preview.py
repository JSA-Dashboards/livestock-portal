"""
The preview iframe must still be a WELL-FORMED HTML DOCUMENT.

The print button is chrome wrapped around the letter, and the tempting way to
add chrome is to concatenate it on the front. That silently breaks the letter:
a doctype that is not the first thing in the document is discarded, and the
whole page renders in quirks mode, where table rows and margins lay out
differently. Both print paths are supposed to produce the same letter, so a
divergence here is invisible until a client gets a page that does not match.

Measured on the real preview in a real browser, 2026-09-30, before the fix:

    document.compatMode == "BackCompat"      (standards is "CSS1Compat")
    document.doctype is None
    the letter's own <meta>, <title> and <style> all inside <body>
    first cash band 102px tall, against 108px in standards mode

These tests pin the STRUCTURE rather than the mechanism, so they keep holding
if the button's markup or styling changes.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP = ROOT / "apps" / "weekly_reports" / "app.py"

BUTTON_TAG = '<button id="jsa-print"'


def _compose():
    """
    The page's own composer, lifted out without importing the page.

    `apps/weekly_reports/app.py` is a Streamlit script -- importing it would
    run the whole letter builder and demand secrets. Exec'ing just the helper
    keeps this a unit test of the thing that actually broke.
    """
    src = APP.read_text(encoding="utf-8")
    parts = []
    for name in ("_PRINT_STYLE", "_PRINT_BUTTON"):
        m = re.search(r'^' + name + r' = """(.*?)"""', src, re.S | re.M)
        assert m, name + " not found in app.py"
        parts.append(name + ' = """' + m.group(1) + '"""')
    m = re.search(r"^def _with_print_button\(doc: str\) -> str:.*?(?=\n\S)",
                  src, re.S | re.M)
    assert m, "_with_print_button not found in app.py"
    ns = {"re": re}
    exec("\n".join(parts) + "\n\n" + m.group(0), ns)
    return ns["_with_print_button"]


LETTER = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'><title>JSA</title>"
    "<style>body{margin:0}</style></head><body><div class='frame'></div>"
    "<p>letter</p></body></html>"
)

# The real letter, reduced to the part that broke the first fix. render.py's
# stylesheet genuinely contains the words "put a background on <body>", so the
# first "<body" in the document is prose inside a CSS comment.
LETTER_WITH_BODY_IN_A_CSS_COMMENT = (
    "<!DOCTYPE html><html><head><title>JSA</title><style>\n"
    "/* z-index -1 puts it under the content, which only works because the\n"
    "   page background lives on <html> -- put a background on <body> and\n"
    "   this disappears underneath it. */\n"
    ".wm { z-index: -1; }\n"
    "</style></head><body class=\"am\"><p>letter</p></body></html>"
)


def test_the_composed_preview_still_starts_with_the_doctype():
    """The whole point. A doctype anywhere but first is thrown away."""
    out = _compose()(LETTER)
    assert out.lstrip().upper().startswith("<!DOCTYPE HTML>"), (
        "the doctype is no longer first -- the preview will render in quirks "
        "mode and stop matching Build PDF"
    )


def test_the_button_style_lands_in_the_head():
    out = _compose()(LETTER)
    head = out[: out.lower().index("</head>")]
    assert "#jsa-print" in head


def test_the_button_itself_lands_inside_the_body():
    out = _compose()(LETTER)
    at = out.index(BUTTON_TAG)
    assert out.lower().index("<body") < at < out.lower().index("</body>")


def test_the_button_survives_a_body_mentioned_in_a_css_comment():
    """
    THE FIRST FIX FAILED HERE, and silently.

    `doc.find("<body")` matched the words "put a background on <body>" inside
    render.py's own stylesheet comment, so the button was inserted into a CSS
    comment and never became an element. The preview rendered perfectly and
    simply had no print button -- the failure mode this repo keeps meeting:
    a search matching prose rather than markup, raising nothing.
    """
    out = _compose()(LETTER_WITH_BODY_IN_A_CSS_COMMENT)
    assert out.index(BUTTON_TAG) > out.index("</style>"), (
        "the button landed inside the stylesheet -- it is inert there"
    )
    assert out.index(BUTTON_TAG) > out.index('<body class="am">')


def test_the_button_is_hidden_when_printing():
    """It is chrome. It must never appear on the client's letter."""
    out = _compose()(LETTER)
    assert re.search(r"@media\s+print\s*\{[^}]*#jsa-print[^}]*display:\s*none", out)


def test_the_letter_is_not_otherwise_altered():
    """Everything the letter said must survive the wrapping, exactly once."""
    out = _compose()(LETTER)
    for fragment in ("<div class='frame'></div>", "<p>letter</p>", "<title>JSA</title>"):
        assert out.count(fragment) == 1


@pytest.mark.parametrize("doc", [
    "<p>no head, no body</p>",
    "<!DOCTYPE html><html><body><p>no head</p></body></html>",
    "<!DOCTYPE html><html><head><title>t</title></head><p>no body tag</p></html>",
])
def test_a_letter_without_a_head_or_body_still_gets_a_button(doc):
    """
    Degrade to prepending rather than losing the button.

    A button in an odd place is cosmetic; a preview with no way to print is
    the one that stops the letter going out.
    """
    out = _compose()(doc)
    assert "jsa-print" in out


def test_the_page_does_not_concatenate_the_chrome_onto_the_front():
    """
    Pins the REGRESSION, not just the fix.

    `_print_ui + html` is the shape that broke it, and it is the shape someone
    reaches for again when adding a second button. Comments and docstrings are
    stripped first: this repo's tests have matched their own prose before.
    """
    src = APP.read_text(encoding="utf-8")
    src = re.sub(r'"""(.*?)"""', "", src, flags=re.S)
    src = re.sub(r"#.*", "", src)
    assert "_print_ui" not in src, "the old front-concatenated chrome is back"
    assert "_with_print_button(html)" in src
