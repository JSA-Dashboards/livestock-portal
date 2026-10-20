#!/usr/bin/env bash
# Install the Cattle Cycles seed-refresh cron on the droplet. Run ON the
# droplet, as root.
#
#   bash install_cattle_cycles_cron.sh            # install
#   bash install_cattle_cycles_cron.sh --check    # report only, change nothing
#
# IDEMPOTENT THROUGHOUT, and it shares the checkout and venv the morning-cutout,
# Mexican-auction, Canadian-livestock and southeastern-retention jobs already
# use. An existing checkout is pulled rather than re-cloned, and the crontab is
# read, appended to and written back -- never replaced -- so the ~25 jobs
# already on this host survive.
#
# It will NOT invent credentials. If the environment is not already set up it
# says exactly what is missing and stops before touching cron, because a job
# installed without credentials fails silently once a month forever -- and once
# a month is the slowest possible way to notice.

set -euo pipefail

REPO_URL="https://github.com/JSA-Dashboards/livestock-portal.git"
DEST="${DEST:-/opt/livestock-portal}"
LOG_GLOB="$DEST/logs/cattle_cycles_*.log"
PY="$DEST/.venv/bin/python"

# MONTHLY, PRIMARY PLUS CATCH-UP.
# NASS publishes Agricultural Prices near the end of each month and the price
# received series runs about a month behind, so there is exactly one new
# observation per series per month and nothing a daily run would catch. The 2nd
# gives the end-of-month release time to reach the bulk dump; the 9th is
# insurance against the 2nd failing or against USDA running late, not
# precision. BLS CPI-U lands mid-month and is picked up by whichever run
# follows it.
#
# The write is idempotent: refresh_cattle_cycles.py skips any period whose
# value is unchanged, so the second run normally costs two fetches and writes
# nothing. That is what lets the schedule be blunt -- no DST arithmetic, no
# holiday calendar to maintain and none to get wrong.
#
# TIMES ARE AMERICA/CHICAGO. The host reports CDT -0500 and its crontab header
# says so. 08:20 sits in the one clear gap on this host's morning: it is past
# the 07:00 beef-trimmings Monday catch-up and the 07:40 Mon/Thu southeastern
# retention job, and 40 minutes ahead of the 09:00 Canadian-livestock fetch.
# This job streams 464MB, so keeping it off another job's shoulder matters more
# here than for the small ones.
#
# IT GOES THROUGH /opt/alerting/cron-alert, AND THAT IS NOT DECORATION. The
# crontab's own header on that box reads: "cron here has no MAILTO and the box
# has no MTA, so a bare entry fails silently." Every job on the host uses the
# wrapper; it mails on a non-zero exit, attaches the matching log, and kills a
# run that hangs past ALERT_TIMEOUT. A bare line would mean nobody ever hears
# that this job died.
ALERT="/opt/alerting/cron-alert"
CRON_LINE="20 8 2,9 * * $ALERT \"Cattle cycles seed\" \"$DEST/logs/cattle_cycles_*.log\" $DEST/deploy/run_cattle_cycles.sh"
CRON_TAG="deploy/run_cattle_cycles.sh"

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
  say "no $DEST/.env yet -- on a bare host, clone $DEST and write .env BEFORE"
  say "running this. The checks below run ahead of the clone, so this script"
  say "refuses rather than bootstraps. That refusal is deliberate."
fi
MISSING=""
for v in USE_SNOWFLAKE SNOWFLAKE_ACCOUNT SNOWFLAKE_USER SNOWFLAKE_ROLE \
         SNOWFLAKE_WAREHOUSE SNOWFLAKE_DATABASE; do
  if [ -n "${!v:-}" ]; then say "$v = set"; else say "$v = MISSING"; MISSING="$MISSING $v"; fi
done
if [ -n "${SNOWFLAKE_PASSWORD:-}" ] || [ -n "${SNOWFLAKE_PRIVATE_KEY:-}" ]; then
  say "credential = set"
else
  say "credential = MISSING (need SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY)"
  MISSING="$MISSING SNOWFLAKE_PASSWORD|SNOWFLAKE_PRIVATE_KEY"
fi
# NO API KEY ON THIS LIST, and that is checked rather than assumed: both feeds
# are keyless. NASS is the public bulk dump at nass.usda.gov/datasets/ and BLS
# is a flat file at download.bls.gov. The southeastern job's list carries
# MARS_API_KEY because it is the only job on this host that reads marsapi;
# nothing here does.
#
# SNOWFLAKE_SCHEMA is deliberately absent. refresh_cattle_cycles.py names its
# table in full, and CLAUDE.md records that setting it breaks nine other
# modules that each default it to the schema they own.

# The committed seed must be in the checkout. Without it the shortfall guard in
# refresh_cattle_cycles.py has nothing to compare a fetch against, so a
# truncated download would write a short series and exit 0.
echo
echo "== committed seed =="
SEEDFILE="$DEST/apps/cattle_cycles/data/cattle_cycles.json"
if [ -f "$SEEDFILE" ]; then
  say "present: $SEEDFILE"
else
  say "MISSING: $SEEDFILE"
  MISSING="$MISSING cattle_cycles.json"
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
  echo "The seed ships with the repo. If $DEST has no checkout at all this is" >&2
  echo "a bare host: clone it and write .env, then re-run. If it does, the" >&2
  echo "checkout is stale -- pull and re-run." >&2
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
  requests pandas snowflake-connector-python

# -- prove it works BEFORE installing the schedule ----------------------------
# The dry run streams the whole 464MB dump, so allow it a few minutes.
echo
echo "== dry run (writes nothing) =="
"$PY" "$DEST/deploy/refresh_cattle_cycles.py" --dry-run

echo
echo "== first real run (writes about 5,058 rows into an empty table) =="
"$PY" "$DEST/deploy/refresh_cattle_cycles.py"

chmod +x "$DEST/deploy/run_cattle_cycles.sh"

# -- crontab: append, never replace -------------------------------------------
echo
echo "== cron =="
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "already present, leaving it alone"
else
  say "appending"
  { crontab -l 2>/dev/null || true; \
    echo "# Cattle Cycles seed -> JSA.CME_FEEDER_CATTLE.CATTLE_CYCLE_PRICES"; \
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
say "table: JSA.CME_FEEDER_CATTLE.CATTLE_CYCLE_PRICES"
say "The page falls back to the committed seed if this table is empty or"
say "unreachable, so a failed install degrades to a frozen series rather than"
say "to a blank chart -- which also means a silent failure here is invisible."
say "Check MAX(RECORDED_AT) in that table, not the chart, to tell it is running."
