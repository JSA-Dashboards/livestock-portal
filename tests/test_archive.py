"""
The published-letter archive.

WHAT IT IS FOR. Until 2026-09-24 nothing kept a published letter: out/ is
gitignored, the build overwrites a render with the same date and session, and
the deployed app's out/ is wiped by every reboot. When the question was finally
asked, the rendered 9/15 and 9/22 letters were gone, and the 9/18 file still on
disk turned out to have been REBUILT on the 23rd -- five days after it was sent.

That last detail is the reason this stores bytes rather than inputs, and the
reason the tests below care about shas: a letter re-rendered later is a
different document, and a good archive must be able to say so.

Everything here runs against a real git repo in tmp_path. Nothing touches the
live archive and nothing hits the network.

    python -m pytest tests/test_archive.py -q
"""
from __future__ import annotations

import json
import subprocess
from datetime import date

import pytest

from letter import archive


@pytest.fixture
def repo(tmp_path):
    """A throwaway archive checkout with no remote."""
    root = tmp_path / "jsa-letter-archive"
    root.mkdir()
    for args in (["init", "-q"],
                 ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "Test"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


@pytest.fixture
def letter(tmp_path):
    html = tmp_path / "letter.html"
    pdf = tmp_path / "letter.pdf"
    html.write_text("<html>the letter as sent</html>", encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.4 fake")
    return html, pdf


ISSUE = date(2026, 9, 23)


def test_it_files_by_year_and_month(repo, letter):
    html, pdf = letter
    r = archive.publish(ISSUE, "am", html, pdf, kind="am",
                        title="JSA AM Daily Cattle Report", push=False, root=repo)
    assert r["ok"] and r["changed"]
    assert (repo / "2026" / "09" / "2026-09-23-am.html").exists()
    assert (repo / "2026" / "09" / "2026-09-23-am.pdf").exists()


def test_the_two_letters_of_a_day_do_not_collide(repo, letter):
    html, pdf = letter
    for session in ("am", "pm"):
        archive.publish(ISSUE, session, html, pdf, push=False, root=repo)
    names = sorted(p.name for p in (repo / "2026" / "09").glob("*.html"))
    assert names == ["2026-09-23-am.html", "2026-09-23-pm.html"]


def test_it_commits(repo, letter):
    html, pdf = letter
    archive.publish(ISSUE, "am", html, pdf, title="JSA AM Daily Cattle Report",
                    push=False, root=repo)
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert "2026-09-23 AM" in log


def test_archiving_the_same_bytes_twice_makes_no_commit(repo, letter):
    """Pressing the button again must be harmless, not a stream of empty commits."""
    html, pdf = letter
    archive.publish(ISSUE, "am", html, pdf, push=False, root=repo)
    before = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=repo,
                            capture_output=True, text=True).stdout.strip()
    second = archive.publish(ISSUE, "am", html, pdf, push=False, root=repo)
    after = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    assert second["ok"] and not second["changed"]
    assert before == after


def test_a_corrected_letter_keeps_the_old_one_in_history(repo, letter):
    """
    THE ARGUMENT FOR A GIT REPO RATHER THAN A FOLDER. Re-publishing a date
    overwrites the file, and the bytes that went out the first time are still
    recoverable. No -v2 filenames to invent.
    """
    html, pdf = letter
    archive.publish(ISSUE, "am", html, pdf, push=False, root=repo)
    html.write_text("<html>the corrected letter</html>", encoding="utf-8")
    r = archive.publish(ISSUE, "am", html, pdf, push=False, root=repo)
    assert r["changed"]

    path = "2026/09/2026-09-23-am.html"
    revs = subprocess.run(["git", "log", "--format=%H", "--", path], cwd=repo,
                          capture_output=True, text=True).stdout.split()
    assert len(revs) == 2
    first = subprocess.run(["git", "show", f"{revs[-1]}:{path}"], cwd=repo,
                           capture_output=True, text=True).stdout
    assert "the letter as sent" in first


def test_the_index_records_what_is_needed_to_find_a_letter(repo, letter):
    html, pdf = letter
    archive.publish(ISSUE, "pm", html, pdf, kind="tuesday",
                    title="JSA PM Daily Cattle Report", push=False, root=repo)
    index = json.loads((repo / "index.json").read_text(encoding="utf-8"))
    entry = index["2026-09-23-pm"]
    assert entry["issue_date"] == "2026-09-23"
    assert entry["session"] == "pm"
    assert entry["kind"] == "tuesday"
    assert entry["weekday"] == "wednesday"
    assert entry["files"]["html"] == "2026/09/2026-09-23-pm.html"
    assert len(entry["sha256"]["html"]) == 16


def test_first_archived_at_survives_a_no_op_republish(repo, letter):
    """It says when the letter was published, which re-pressing must not rewrite."""
    html, pdf = letter
    archive.publish(ISSUE, "am", html, pdf, push=False, root=repo)
    first = json.loads((repo / "index.json").read_text())["2026-09-23-am"]["archived_at"]
    archive.publish(ISSUE, "am", html, pdf, push=False, root=repo)
    again = json.loads((repo / "index.json").read_text())["2026-09-23-am"]["archived_at"]
    assert first == again


def test_no_checkout_is_a_reason_not_a_traceback(tmp_path, letter):
    """
    Streamlit Cloud has no clone and no push credentials. Archiving runs at the
    end of a letter and must never cost the letter.
    """
    html, pdf = letter
    r = archive.publish(ISSUE, "am", html, pdf, push=False, root=tmp_path / "nope")
    assert r["ok"] is False
    assert "no archive" in r["reason"]


def test_a_missing_render_is_reported(repo, tmp_path):
    r = archive.publish(ISSUE, "am", tmp_path / "gone.html", None, push=False, root=repo)
    assert r["ok"] is False and "nothing to archive" in r["reason"]


def test_html_only_is_archivable(repo, letter):
    """--html-only is a real mode; it must not be refused for lacking a PDF."""
    html, _ = letter
    r = archive.publish(ISSUE, "am", html, None, push=False, root=repo)
    assert r["ok"] and r["changed"]
    assert (repo / "2026" / "09" / "2026-09-23-am.html").exists()
    assert not (repo / "2026" / "09" / "2026-09-23-am.pdf").exists()


def test_the_archive_is_never_this_public_repo():
    """
    These are letters paying clients receive and livestock-portal is public.
    The default must point outside it.
    """
    portal = archive.Path(archive.__file__).resolve().parents[1]
    assert archive.DEFAULT_DIR.resolve() != portal
    assert portal not in archive.DEFAULT_DIR.resolve().parents
