#!/usr/bin/env bash
# run_ca_livestock.sh — AMS 3213 Weekly Canadian Livestock and Poultry Summary,
# invoked by cron on the Droplet: /opt/livestock-portal is a git clone of this
# repo.
#
# WHY A WRAPPER AND NOT JUST A PYTHON LINE IN THE CRONTAB. The credentials on
# that host live in a .env FILE beside the code, not in root's environment --
# how beef-trimmings-dashboard's deploy/run_fetch.sh has run there since
# 2026-10-04. cron gives a job almost no environment, so a crontab line calling
# python directly gets no MARS_API_KEY and no Snowflake block: the job exits 1
# on every run, or worse, installs cleanly and records nothing while looking
# perfectly healthy. Sourcing .env is the whole reason this file exists.
#
# Deliberately the same shape as run_fetch.sh, run_am_cutout.sh and
# run_mx_auction.sh -- same /opt/<repo> clone, same .venv, same flock, same
# logs/ directory and 30-day prune. The droplet's crontab, read 2026-10-07,
# shows ten jobs on exactly this pattern. A job inventing its own conventions
# on a host that already has one is how the next person finds two
# half-documented mechanisms.
#
# IDEMPOTENT, so the schedule can be blunt. ca_livestock fetches the whole
# published history every run and banks only what is absent or changed, so a
# day with no new report writes nothing and a missed day is recovered by the
# next one. See the module docstring for why daily beats Tuesday-only on a
# weekly report.
set -uo pipefail

APP_DIR="${APP_DIR:-/opt/livestock-portal}"
VENV="$APP_DIR/.venv"
LOG_DIR="$APP_DIR/logs"

# cd BEFORE creating anything, so a wrong APP_DIR fails instead of scattering a
# logs/ directory somewhere it does not belong.
cd "$APP_DIR" || { echo "APP_DIR $APP_DIR missing" >&2; exit 1; }

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/ca_livestock_$(date +%Y%m%d_%H%M%S).log"

# THE MISSING-flock CASE HAS TO BE HANDLED EXPLICITLY. `if ! flock -n 9` reads
# as "could not take the lock" when flock is simply absent -- command-not-found
# is 127, `!` makes that true, and the job exits 0 having done nothing, every
# run, looking healthy.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOG_DIR/.ca_livestock.lock"
    if ! flock -n 9; then
        echo "$(date -Is) another run is in progress — skipping" >>"$LOG"
        exit 0
    fi
else
    echo "$(date -Is) flock not available — running without a lock" >&2
fi

# SNOWFLAKE_SCHEMA is irrelevant here whatever .env holds: ca_prices names
# JSA.CME_FEEDER_CATTLE.CA_LIVESTOCK_PRICES and .CA_SLAUGHTER in full and takes
# no part in the nine-module collision CLAUDE.md documents at the top.
if [ ! -f .env ]; then
    echo "$(date -Is) no .env in $APP_DIR — nothing would be recorded" >&2
    exit 1
fi
set -a; source .env; set +a

rc=0
{
    echo "=== ca livestock start $(date -Is) ==="
    "$VENV/bin/python3" deploy/ca_livestock.py
    rc=$?
    echo "=== ca livestock finished $(date -Is) rc=$rc ==="
} >>"$LOG" 2>&1

# Re-surface a failure on stderr and EXIT NON-ZERO, because that is what
# /opt/alerting/cron-alert keys on -- the crontab's own header says this box
# has no MAILTO and no MTA, so plain cron mails nothing and a bare entry fails
# SILENTLY. The exit code is the entire alerting contract here.
if [ "$rc" -ne 0 ]; then
    echo "ca_livestock failed rc=$rc — see $LOG" >&2
    tail -n 5 "$LOG" >&2
fi

find "$LOG_DIR" -name 'ca_livestock_*.log' -mtime +30 -delete 2>/dev/null || true

exit "$rc"
