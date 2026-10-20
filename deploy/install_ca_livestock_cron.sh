#!/usr/bin/env bash
# Install the Canadian livestock (AMS 3213) cron on the droplet. Run ON the
# droplet, as root.
#
#   bash install_ca_livestock_cron.sh            # install
#   bash install_ca_livestock_cron.sh --check    # report only, change nothing
#
# IDEMPOTENT THROUGHOUT, and it shares the checkout and venv the morning-cutout
# and Mexican-auction jobs already use. An existing checkout is pulled rather
# than re-cloned, and the crontab is read, appended to and written back --
# never replaced -- so the ~25 jobs already on this host survive.
#
# It will NOT invent credentials. If the environment is not already set up it
# says exactly what is missing and stops before touching cron, because a job
# installed without credentials fails silently once a day forever.

set -euo pipefail

REPO_URL="https://github.com/JSA-Dashboards/livestock-portal.git"
DEST="${DEST:-/opt/livestock-portal}"
LOG_GLOB="$DEST/logs/ca_livestock_*.log"
PY="$DEST/.venv/bin/python"

# TWICE A DAY, EVERY DAY, FOR A WEEKLY REPORT -- measured, not guessed.
# Across all 121 publications on file:
#
#     weekday   Tue 105, Mon 11, Wed 3, Thu 1, Fri 1
#     hour      06 (61), 07 (42), 08 (3), 04 (2), 09 (1),
#               11 (3), 12 (1), 13 (1), 14 (6), 15 (1)
#     lag       9-17 days after the week ends, median 10
#
# So a Tuesday-only job would miss 16 weeks in 121 until the following Tuesday,
# and one pinned hour would miss the dozen that land after 11:00. The 09:00 run
# clears ~90% of publications under EITHER reading of the feed's timezone (AMS
# publishes out of Washington DC; this host runs Central), and 16:00 catches
# the stragglers the same day instead of the next.
#
# ca_livestock fetches the full published history every run and banks only what
# is absent or changed, so the six days a week with no new report cost two
# small requests and write nothing. That is what makes a blunt schedule safe,
# and it means no DST arithmetic and no holiday calendar to maintain.
#
# TIMES ARE AMERICA/CHICAGO. The host reports CDT -0500 and its crontab header
# says so.
#
# IT GOES THROUGH /opt/alerting/cron-alert, AND THAT IS NOT DECORATION. The
# crontab's own header on that box reads: "cron here has no MAILTO and the box
# has no MTA, so a bare entry fails silently." All ~25 jobs on the host use the
# wrapper; it mails on a non-zero exit, attaches the matching log, and kills a
# run that hangs past ALERT_TIMEOUT. A bare line would mean nobody ever hears
# that this job died.
ALERT="/opt/alerting/cron-alert"
CRON_LINE="0 9,16 * * * $ALERT \"Canadian livestock (AMS 3213)\" \"$DEST/logs/ca_livestock_*.log\" $DEST/deploy/run_ca_livestock.sh"
CRON_TAG="deploy/run_ca_livestock.sh"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '  %s\n' "$*"; }

echo "== what is already here =="
say "host:    $(hostname)"
say "date:    $(date '+%Y-%m-%d %H:%M:%S %Z') (host local; crontab is America/Chicago)"
say "checkout: $([ -d "$DEST/.git" ] && echo "$DEST" || echo 'absent')"
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "cron:    already installed"
else
  say "cron:    not installed"
fi
echo "  existing crontab:"
crontab -l 2>/dev/null | sed 's/^/    /' || echo "    (none)"

# -- credentials, by presence only; never print a secret ----------------------
#
# SOURCED FROM $DEST/.env, NOT FROM THE SHELL. Every repo on this host keeps
# its block in a .env beside the code, and root's environment carries none of
# it. An earlier version of the sibling installer read exported variables only,
# so a correctly configured droplet reported every one MISSING.
echo
echo "== environment =="
if [ -f "$DEST/.env" ]; then
  say "reading $DEST/.env"
  set -a; . "$DEST/.env"; set +a
else
  say "no $DEST/.env yet -- checking the exported environment instead."
  say "ON A BARE HOST THAT IS THE WAY IN: export the block and this clones"
  say "$DEST itself. Verified 2026-10-20 by running the gate against an empty"
  say "DEST -- it reached the clone. Only install_southeast_cron.sh and"
  say "install_cattle_cycles_cron.sh genuinely cannot bootstrap, because they"
  say "need a file that exists only once the checkout does."
fi
MISSING=""
# MARS_API_KEY IS IN THIS LIST AND IS THE ONE THE SIBLING JOBS DO NOT NEED.
# mx_auction scrapes a public site and am_cutout fetches a public PDF; this job
# calls marsapi.ams.usda.gov, which is authenticated. Without the key every run
# exits 1 before fetching -- loudly, which is the good case, but only because
# this check exists to stop it being installed that way at all.
for v in MARS_API_KEY USE_SNOWFLAKE SNOWFLAKE_ACCOUNT SNOWFLAKE_USER \
         SNOWFLAKE_ROLE SNOWFLAKE_WAREHOUSE SNOWFLAKE_DATABASE; do
  if [ -n "${!v:-}" ]; then say "$v = set"; else say "$v = MISSING"; MISSING="$MISSING $v"; fi
done
if [ -n "${SNOWFLAKE_PASSWORD:-}" ] || [ -n "${SNOWFLAKE_PRIVATE_KEY:-}" ]; then
  say "credential = set"
else
  say "credential = MISSING (need SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY)"
  MISSING="$MISSING SNOWFLAKE_PASSWORD|SNOWFLAKE_PRIVATE_KEY"
fi
# SNOWFLAKE_SCHEMA is deliberately absent from that list. ca_prices.py names
# both its tables in full, so it needs none -- and CLAUDE.md records that
# setting it breaks nine other modules that each default it to the schema they
# own.

if [ "$CHECK_ONLY" = "1" ]; then
  echo
  echo "== --check only, nothing changed =="
  exit 0
fi

if [ -n "$MISSING" ]; then
  echo
  echo "STOPPING: missing env:$MISSING" >&2
  echo "Put these in $DEST/.env (the same block the am_cutout job uses, plus" >&2
  echo "MARS_API_KEY, which this job needs and those two do not)." >&2
  echo "Nothing was changed." >&2
  exit 1
fi

# A job whose failures nobody hears about is worse than one that is not
# installed, so this is a hard stop rather than a warning.
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
# The same list the sibling installers use, because the venv is shared. Only
# requests and the connector are needed here; installing the full set keeps one
# environment rather than three that can drift.
say "installing deps"
"$DEST/.venv/bin/pip" install --quiet --upgrade \
  requests pypdf pandas snowflake-connector-python

# -- prove it works BEFORE installing the schedule ----------------------------
echo
echo "== dry run (writes nothing) =="
"$PY" "$DEST/deploy/ca_livestock.py" --dry-run

echo
echo "== first real run =="
# THE FIRST RUN BACKFILLS THE WHOLE SERIES -- 119 weeks, ~3,300 price rows and
# ~640 slaughter rows, in one request per section. Every run after it writes
# nothing until a new week publishes. Expect this one to take a minute and the
# rest to take seconds.
"$PY" "$DEST/deploy/ca_livestock.py"

chmod +x "$DEST/deploy/run_ca_livestock.sh"

# -- crontab: append, never replace -------------------------------------------
echo
echo "== cron =="
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "already present, leaving it alone"
else
  say "appending"
  { crontab -l 2>/dev/null || true; \
    echo "# Canadian livestock (AMS 3213) -> JSA.CME_FEEDER_CATTLE.CA_LIVESTOCK_PRICES / .CA_SLAUGHTER"; \
    echo "$CRON_LINE"; } | crontab -
fi

# READ IT BACK. THE WRITE IS NOT THE INSTALL.
#
# The sibling installer printed "appending", piped into `crontab -` and went
# straight to its done banner. A write that never took therefore read as a
# clean install and SAID SO -- which is what told Ross the Mexican job was
# scheduled when the droplet's crontab held nothing. The proof it had not was
# in the data rather than the installer's output: every row in
# MX_AUCTION_PRICES carried RECORDED_BY = mx_auction@JSA-Nitro2, his desktop.
#
# A trailing `crontab -l | grep` is cosmetic: its EMPTY output looks exactly
# like a successful one. A check whose failure is indistinguishable from its
# success is not a check.
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
say "logs: $LOG_GLOB (written by the wrapper, pruned at 30 days)"
say "tables: JSA.CME_FEEDER_CATTLE.CA_LIVESTOCK_PRICES"
say "        JSA.CME_FEEDER_CATTLE.CA_SLAUGHTER"
say "AMS keeps 2024-06-01 forward and nothing earlier; the first run has it all."
say "VERIFY FROM THE DATA, NOT THIS OUTPUT: RECORDED_BY on the newest rows"
say "should read ca_livestock@<this host>, not ca_livestock@JSA-Nitro2."
