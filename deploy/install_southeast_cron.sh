#!/usr/bin/env bash
# Install the southeastern retention-series cron on the droplet. Run ON the
# droplet, as root.
#
#   bash install_southeast_cron.sh            # install
#   bash install_southeast_cron.sh --check    # report only, change nothing
#
# IDEMPOTENT THROUGHOUT, and it shares the checkout and venv the morning-cutout
# and Mexican-auction jobs already use. An existing checkout is pulled rather
# than re-cloned, and the crontab is read, appended to and written back --
# never replaced -- so the ~25 jobs already on this host survive.
#
# It will NOT invent credentials. If the environment is not already set up it
# says exactly what is missing and stops before touching cron, because a job
# installed without credentials fails silently once a week forever.

set -euo pipefail

REPO_URL="https://github.com/JSA-Dashboards/livestock-portal.git"
DEST="${DEST:-/opt/livestock-portal}"
LOG_GLOB="$DEST/logs/southeast_retention_*.log"
PY="$DEST/.venv/bin/python"

# TWICE A WEEK, AND THAT IS GENEROUS RATHER THAN CASUAL.
# This series is ANNUAL. Nineteen bars, of which exactly one -- the current
# year -- can move at all, and it moves by a few thousandths as each week's
# sales join a year-long median. There is nothing a daily run would catch that
# a Monday run does not. Thursday is insurance against Monday failing, not
# precision.
#
# The write is idempotent: refresh_southeast.py skips any year whose ratio and
# sample are unchanged, so the Thursday run normally costs seven MARS fetches
# and writes nothing. That is what lets the schedule be blunt -- no DST
# arithmetic, no holiday calendar to maintain and none to get wrong.
#
# TIMES ARE AMERICA/CHICAGO. The host reports CDT -0500 and its crontab header
# says so. 07:40 keeps it clear of the 07:00 beef-trimmings Monday catch-up.
#
# IT GOES THROUGH /opt/alerting/cron-alert, AND THAT IS NOT DECORATION. The
# crontab's own header on that box reads: "cron here has no MAILTO and the box
# has no MTA, so a bare entry fails silently." Every job on the host uses the
# wrapper; it mails on a non-zero exit, attaches the matching log, and kills a
# run that hangs past ALERT_TIMEOUT. A bare line would mean nobody ever hears
# that this job died.
ALERT="/opt/alerting/cron-alert"
CRON_LINE="40 7 * * 1,4 $ALERT \"Southeastern retention series\" \"$DEST/logs/southeast_retention_*.log\" $DEST/deploy/run_southeast_retention.sh"
CRON_TAG="deploy/run_southeast_retention.sh"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '  %s\n' "$*"; }

echo "== what is already here =="
say "host:     $(hostname)"
say "date:     $(date '+%Y-%m-%d %H:%M:%S %Z') (host local; crontab is America/Chicago)"
say "checkout: $([ -d "$DEST/.git" ] && echo "$DEST" || echo 'absent')"
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "cron:     already installed"
else
  say "cron:     not installed"
fi
echo "  existing crontab:"
crontab -l 2>/dev/null | sed 's/^/    /' || echo "    (none)"

# -- credentials, by presence only; never print a secret ----------------------
echo
echo "== environment =="
if [ -f "$DEST/.env" ]; then
  say "reading $DEST/.env"
  set -a; . "$DEST/.env"; set +a
else
  say "no $DEST/.env yet (it is created with the checkout below on a new host)"
fi
MISSING=""
for v in USE_SNOWFLAKE SNOWFLAKE_ACCOUNT SNOWFLAKE_USER SNOWFLAKE_ROLE \
         SNOWFLAKE_WAREHOUSE SNOWFLAKE_DATABASE MARS_API_KEY; do
  if [ -n "${!v:-}" ]; then say "$v = set"; else say "$v = MISSING"; MISSING="$MISSING $v"; fi
done
if [ -n "${SNOWFLAKE_PASSWORD:-}" ] || [ -n "${SNOWFLAKE_PRIVATE_KEY:-}" ]; then
  say "credential = set"
else
  say "credential = MISSING (need SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY)"
  MISSING="$MISSING SNOWFLAKE_PASSWORD|SNOWFLAKE_PRIVATE_KEY"
fi
# MARS_API_KEY is on that list and the other installers' lists do not carry it,
# because this is the first job on this host that reads marsapi. It is also the
# whole reason the job lives here rather than on the page: marsapi rejects
# Streamlit Community Cloud's IPs, so the portal cannot fetch its own MARS half.
#
# SNOWFLAKE_SCHEMA is deliberately absent. refresh_southeast.py names its table
# in full, and CLAUDE.md records that setting it breaks nine other modules that
# each default it to the schema they own.

# The frozen legacy half must be in the checkout. Without it the job has only
# the MARS years and would quietly publish a series starting in 2019 -- which
# is exactly the chart this panel exists to improve on, and it would look fine.
echo
echo "== frozen legacy half =="
FROZEN="$DEST/apps/us_cow_herd/data/southeast_legacy.json"
if [ -f "$FROZEN" ]; then
  say "present: $FROZEN"
else
  say "MISSING: $FROZEN"
  MISSING="$MISSING southeast_legacy.json"
fi

if [ "$CHECK_ONLY" = "1" ]; then
  echo
  echo "== --check only, nothing changed =="
  exit 0
fi

if [ -n "$MISSING" ]; then
  echo
  echo "STOPPING: missing:$MISSING" >&2
  echo "Put the env in $DEST/.env (the same block the am_cutout job uses);" >&2
  echo "the frozen file ships with the repo, so a miss there means a stale" >&2
  echo "checkout -- pull and re-run." >&2
  echo "Nothing was changed." >&2
  exit 1
fi

if [ ! -x "$ALERT" ]; then
  echo
  echo "STOPPING: $ALERT is missing or not executable." >&2
  echo "Every job on this host is wrapped in it; cron here mails nothing on" >&2
  echo "its own, so an unwrapped job fails silently. Nothing was changed." >&2
  exit 1
fi

# -- checkout -----------------------------------------------------------------
echo
echo "== code =="
if [ -d "$DEST/.git" ]; then
  say "pulling $DEST"
  git -C "$DEST" pull --ff-only
else
  say "cloning into $DEST"
  git clone --depth 50 "$REPO_URL" "$DEST"
fi

if [ ! -x "$PY" ]; then
  say "creating venv"
  python3 -m venv "$DEST/.venv"
fi
say "installing deps"
"$DEST/.venv/bin/pip" install --quiet --upgrade \
  requests pypdf pandas snowflake-connector-python

# -- prove it works BEFORE installing the schedule ----------------------------
echo
echo "== dry run (writes nothing) =="
"$PY" "$DEST/deploy/refresh_southeast.py" --dry-run

echo
echo "== first real run =="
"$PY" "$DEST/deploy/refresh_southeast.py"

chmod +x "$DEST/deploy/run_southeast_retention.sh"

# -- crontab: append, never replace -------------------------------------------
echo
echo "== cron =="
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "already present, leaving it alone"
else
  say "appending"
  { crontab -l 2>/dev/null || true; \
    echo "# Southeastern retention series -> JSA.CME_FEEDER_CATTLE.SOUTHEAST_RETENTION"; \
    echo "$CRON_LINE"; } | crontab -
fi

# READ IT BACK. THE WRITE IS NOT THE INSTALL.
#
# A sibling installer on this host printed "appending", piped into `crontab -`
# and went straight to its done banner. A write that never took therefore read
# as a clean install and SAID SO -- which is what told Ross a job was scheduled
# when the droplet's crontab held nothing. A trailing `crontab -l | grep` is
# not enough either: its EMPTY output looks exactly like a successful one. A
# check whose failure is indistinguishable from its success is not a check.
installed=$(crontab -l 2>/dev/null | grep -cF "$CRON_TAG" || true)
if [ "$installed" -ne 1 ]; then
  echo >&2
  echo "FAILED: expected 1 line matching '$CRON_TAG', found $installed." >&2
  echo "The crontab did not take. NOTHING IS SCHEDULED; do not assume it is." >&2
  echo "  crontab now reads:" >&2
  crontab -l 2>/dev/null | sed 's/^/    /' >&2 || echo "    (unreadable)" >&2
  exit 1
fi
say "verified: 1 line present in the live crontab"

echo
echo "== done =="
say "logs:  $LOG_GLOB (written by the wrapper, pruned at 30 days)"
say "table: JSA.CME_FEEDER_CATTLE.SOUTHEAST_RETENTION"
say "The page falls back to the committed JSON if this table is empty or"
say "unreachable, so a failed install degrades to a frozen series rather than"
say "to a blank chart -- which also means a silent failure here is invisible."
say "Check RECORDED_AT in that table, not the chart, to tell it is running."
