"""The Canadian ingest must reimplement nothing the page already does.

`deploy/ca_livestock.py` imports apps/canadian_feeder_cattle/ca_prices.py by
path and calls it. If it ever grows its own parser, the cron and the page can
disagree about what a report says -- and the cron runs unattended, where nobody
would see it drift. That is the snowflake_db.py-times-five problem with no
renderer to catch it, and deploy/bank_am_cutout.py has the same test for the
same reason.

    python -m pytest tests/test_ca_livestock.py -q
"""

import ast
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEPLOY = os.path.join(_HERE, "..", "deploy")
_APP = os.path.join(_HERE, "..", "apps", "canadian_feeder_cattle")

JOB = os.path.join(_DEPLOY, "ca_livestock.py")
WRAPPER = os.path.join(_DEPLOY, "run_ca_livestock.sh")
INSTALLER = os.path.join(_DEPLOY, "install_ca_livestock_cron.sh")
MODULE = os.path.join(_APP, "ca_prices.py")

sys.path.insert(0, _APP)
import ca_prices as cap  # noqa: E402


def _tree(path):
    return ast.parse(open(path, encoding="utf-8").read())


def _defs(path):
    return {n.name for n in ast.walk(_tree(path))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _text(path):
    return open(path, encoding="utf-8").read()


# ── the job owns no arithmetic ──────────────────────────────────────────────

def test_the_job_defines_none_of_the_parsers():
    """Asserted by AST rather than grep, because the job's own docstring names
    these functions when it explains the rule -- the mistake
    tests/test_rundown.py made first time and records."""
    owned = {"parse_prices", "parse_slaughter", "feeder_ladder", "price_change",
             "slaughter_summary", "missing_weeks", "staleness", "iso",
             "latest_week", "ensure_table", "bank_prices", "bank_slaughter",
             "_dedupe", "_date", "_num"}
    clash = _defs(JOB) & owned
    assert not clash, f"ca_livestock redefines {sorted(clash)} instead of importing them"


def test_the_job_loads_ca_prices_by_path_under_a_private_name():
    src = _text(JOB)
    assert "spec_from_file_location" in src
    assert "_ca_livestock_prices" in src, "a generic module name can collide"
    assert "ca_prices.py" in src


def test_the_job_never_hardcodes_the_slug_or_sections():
    """One definition of what report this is. A second spelling in the job is
    how a section rename fixes the page and leaves the cron fetching nothing."""
    src = _text(JOB)
    assert '"3213"' not in src and "'3213'" not in src, "slug hardcoded in the job"
    assert "Report Detail Price" not in src, "section name hardcoded in the job"
    assert "Report Detail Slaughter" not in src, "section name hardcoded in the job"
    assert "cap.SLUG" in src and "cap.SECTION_PRICE" in src


def test_the_job_is_the_only_side_with_requests():
    """The page may not acquire an HTTP path; the ingest must have one. Both
    halves of that rule are load-bearing and this pins the pair."""
    job_imports = set()
    for n in ast.walk(_tree(JOB)):
        if isinstance(n, ast.Import):
            job_imports.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            job_imports.add(n.module.split(".")[0])
    assert "requests" in job_imports, "the ingest must be able to fetch"

    page_imports = set()
    for n in ast.walk(_tree(MODULE)):
        if isinstance(n, ast.Import):
            page_imports.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            page_imports.add(n.module.split(".")[0])
    assert "requests" not in page_imports, "the page must not be able to fetch"


# ── the wrapper ─────────────────────────────────────────────────────────────

def test_the_wrapper_sources_dotenv_before_running_python():
    """cron gives a job almost no environment. A crontab line calling python
    directly gets no MARS_API_KEY and no Snowflake block, and the job records
    nothing while looking installed. Sourcing .env is why the wrapper exists."""
    src = _text(WRAPPER)
    assert "source .env" in src or ". .env" in src
    assert src.index("source .env") < src.index("deploy/ca_livestock.py")
    assert 'if [ ! -f .env ]' in src, "a missing .env must stop the run, not be ignored"


def test_the_wrapper_handles_a_missing_flock_explicitly():
    """`if ! flock -n 9` reads as "could not take the lock" when flock is simply
    absent -- command-not-found is 127, `!` makes that true, and the job exits 0
    having done nothing, every run, looking healthy."""
    src = _text(WRAPPER)
    assert "command -v flock" in src


def test_the_wrapper_cds_before_creating_anything():
    """A wrong APP_DIR must fail, not scatter a logs/ directory elsewhere."""
    src = _text(WRAPPER)
    assert src.index('cd "$APP_DIR"') < src.index('mkdir -p "$LOG_DIR"')


def test_the_wrapper_exits_nonzero_on_failure():
    """The exit code is the entire alerting contract on that host -- cron there
    has no MAILTO and the box has no MTA."""
    src = _text(WRAPPER)
    assert 'exit "$rc"' in src


# ── the installer ───────────────────────────────────────────────────────────

def test_the_installer_refuses_to_write_a_bare_crontab_entry():
    """All ~25 jobs on that host run under /opt/alerting/cron-alert because
    plain cron there mails nothing. A bare entry fails silently for ever."""
    src = _text(INSTALLER)
    assert "/opt/alerting/cron-alert" in src
    assert 'if [ ! -x "$ALERT" ]' in src, "a missing wrapper must be a hard stop"
    assert "$ALERT" in src[src.index("CRON_LINE="):src.index("CRON_LINE=") + 400]


def test_the_installer_requires_the_mars_key():
    """The sibling jobs do not need it -- mx_auction scrapes a public site and
    am_cutout fetches a public PDF -- so it is the one credential an installer
    copied from either of them would omit, and the job would exit 1 every run."""
    src = _text(INSTALLER)
    required = re.search(r"for v in (.+?); do", src, re.S)
    assert required, "could not find the required-env loop"
    assert "MARS_API_KEY" in required.group(1)


def test_the_installer_reads_the_crontab_back():
    """The write is not the install. The sibling printed "appending" and went
    straight to its done banner; a write that never took read as a clean
    install and said so."""
    src = _text(INSTALLER)
    assert "installed=$(crontab -l" in src
    assert '"$installed" -ne 1' in src
    assert src.index("installed=$(crontab -l") > src.index("| crontab -")


def test_the_installer_appends_rather_than_replacing():
    """~25 jobs already live on that host."""
    src = _text(INSTALLER)
    assert "crontab -l 2>/dev/null || true" in src, "must append to the existing crontab"


def test_the_installer_never_sets_snowflake_schema():
    """Nine modules each default it to the schema they own; setting it breaks
    all nine. ca_prices names both tables in full and needs none."""
    for path in (INSTALLER, WRAPPER, JOB):
        src = _text(path)
        assert not re.search(r"^\s*(export\s+)?SNOWFLAKE_SCHEMA=", src, re.M), \
            f"{os.path.basename(path)} sets SNOWFLAKE_SCHEMA"


def test_the_installer_dry_runs_before_scheduling():
    """Prove it works before installing a schedule, not after."""
    src = _text(INSTALLER)
    assert "--dry-run" in src
    assert src.index("--dry-run") < src.index("| crontab -")


def test_check_mode_changes_nothing():
    """--check must exit before the clone, the pip install and the crontab."""
    src = _text(INSTALLER)
    stop = src.index('CHECK_ONLY" = "1"')
    # "pip install" is spelled `"$DEST/.venv/bin/pip" install` -- match the verb.
    for after in ("git clone", "bin/pip\" install", "| crontab -", "--dry-run"):
        assert src.index(after) > stop, f"--check reaches {after}"


def test_the_schedule_is_daily_and_goes_through_the_alert_wrapper():
    """Tuesday-dominant but not Tuesday-only: 16 of 121 publications land on
    another weekday, and a dozen after 11:00. Daily is measured, not lazy."""
    src = _text(INSTALLER)
    # The line embeds ESCAPED quotes around the job name and log glob, so a
    # [^"]+ capture stops at the first one and silently returns a fragment --
    # which is how the first version of this test "passed" a truncated string.
    # Take the whole assignment line instead.
    line = next(l for l in src.splitlines() if l.startswith("CRON_LINE="))
    fields = line.split('"', 1)[1].split()
    assert fields[2:5] == ["*", "*", "*"], f"not a daily schedule: {line}"
    assert "9,16" in fields[1], "expected the measured 09:00 primary + 16:00 catch-up"
    assert "$ALERT" in line, "the schedule must run through /opt/alerting/cron-alert"
    assert 'ALERT="/opt/alerting/cron-alert"' in src
