#!/usr/bin/env bash
# Install the morning-cutout cron on the droplet. Run ON the droplet, as root.
#
#   bash install_am_cutout_cron.sh            # install
#   bash install_am_cutout_cron.sh --check    # report only, change nothing
#
# IDEMPOTENT THROUGHOUT. It re-runs safely: an existing checkout is pulled
# rather than re-cloned, and the crontab line is added only if it is not
# already there. The crontab is read, appended to and written back -- it is
# never replaced, so the beef-trimmings job already on this host survives.
#
# It will NOT invent Snowflake credentials. If the environment is not already
# set up it says exactly what is missing and stops before touching cron,
# because a job installed without credentials fails silently once a day
# forever.

set -euo pipefail

REPO_URL="https://github.com/JSA-Dashboards/livestock-portal.git"
DEST="${DEST:-/opt/livestock-portal}"
LOG="${LOG:-/var/log/am_cutout.log}"
PY="$DEST/.venv/bin/python"

# stdout to the log, stderr deliberately NOT redirected: cron mails stderr and
# a non-zero exit is the whole alerting story. A 2>&1 here would silence every
# failure this job can have.
# Calls the WRAPPER, not python directly: the Snowflake block on that host is
# in $DEST/.env, and cron gives a job almost no environment. A bare python
# line installs cleanly and then records nothing, every run, for ever.
#
# The window is wide because the droplet's own timezone is not assumed --
# beef-trimmings-dashboard documents its schedule in CT while this script
# reports UTC, and the job is idempotent, so a sweep that covers both readings
# costs a few no-op PDF fetches and removes the guess. The installer prints
# the host's actual timezone below; tighten this once it is known.
# EVERY LINE ON THIS HOST GOES THROUGH /opt/alerting/cron-alert, and that is
# not decoration. The droplet's crontab says so in its own header: cron here
# has no MAILTO and the box has no MTA, so a BARE ENTRY FAILS SILENTLY. The
# wrapper emails on a non-zero exit, attaches the matching log, and kills a
# job that hangs past ALERT_TIMEOUT. An earlier version of this installer
# wrote a bare entry and asserted that cron mails stderr -- it does not, here.
#
# TIMES ARE AMERICA/CHICAGO. Confirmed 2026-10-07: the host reports CDT -0500
# and the crontab header states it outright. The earlier 11-22 sweep was
# hedging a timezone that is now known, so it is gone.
#
# 11:15 against a ~10:55 CT release, plus an afternoon catch-up for the days
# USDA runs late -- the primary-plus-catch-up shape the beef-trimmings fetch
# already uses (Fri 16:30 + Mon 07:00). Mon-Fri: there is no weekend morning
# cutout, and bank() would no-op anyway.
ALERT="/opt/alerting/cron-alert"
LOGGLOB="$DEST/logs/am_cutout_*.log"
CRON_LINE="15 11 * * 1-5 $ALERT 'Beef cutout morning bank' '$LOGGLOB' $DEST/deploy/run_am_cutout.sh"
CRON_LINE2="0 14 * * 1-5 $ALERT 'Beef cutout morning bank (catch-up)' '$LOGGLOB' $DEST/deploy/run_am_cutout.sh"
CRON_TAG="deploy/run_am_cutout.sh"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '  %s\n' "$*"; }

echo "== what is already here =="
say "host:    $(hostname)"
say "date:    $(date -u '+%Y-%m-%d %H:%M:%SZ') (UTC)"
say "host tz: $(date '+%Z %z')  <- the crontab window assumes nothing; tighten it once known"
say "checkout: $([ -d "$DEST/.git" ] && echo "$DEST" || echo 'absent')"
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "cron:    already installed"
else
  say "cron:    not installed"
fi
echo "  existing crontab:"
crontab -l 2>/dev/null | sed 's/^/    /' || echo "    (none)"

# -- credentials, by presence only; never print a secret ----------------------
echo
echo "== snowflake environment =="
# SOURCE $DEST/.env FIRST. Checking only exported variables was wrong: this
# host keeps the block in a .env file beside the code (the convention
# beef-trimmings-dashboard's deploy/run_fetch.sh has used since 2026-10-04),
# so a properly set up droplet reported every variable MISSING and this
# refused to install.
if [ -f "$DEST/.env" ]; then
  say "sourcing $DEST/.env"
  set -a; . "$DEST/.env"; set +a
else
  say "no $DEST/.env yet -- checking the exported environment instead"
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
# SNOWFLAKE_SCHEMA is deliberately absent from that list. am_cutout names its
# table in full, so it needs none -- and CLAUDE.md records that setting it
# breaks five other modules that each default it to the schema they own.

if [ "$CHECK_ONLY" = "1" ]; then
  echo
  echo "== --check only, nothing changed =="
  exit 0
fi

if [ ! -x "$ALERT" ]; then
  echo
  echo "STOPPING: $ALERT is missing or not executable." >&2
  echo "Every job on this host is alerted through it; cron here has no" >&2
  echo "MAILTO and the box has no MTA, so a bare entry fails SILENTLY." >&2
  echo "Nothing was changed." >&2
  exit 1
fi

if [ -n "$MISSING" ]; then
  echo
  echo "STOPPING: missing env:$MISSING" >&2
  echo "Export these (the same block the beef-trimmings job uses) and re-run." >&2
  echo "Nothing was changed." >&2
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
chmod +x "$DEST/deploy/run_am_cutout.sh"

echo
echo "== dry run (writes nothing) =="
"$PY" "$DEST/deploy/bank_am_cutout.py" --dry-run

echo
echo "== first real run =="
"$PY" "$DEST/deploy/bank_am_cutout.py"

# -- crontab: append, never replace -------------------------------------------
#
# AND THEN READ IT BACK. The previous version printed "appending", piped into
# `crontab -`, and went straight to "== done ==" -- the only thing resembling
# a check was a cosmetic `grep` whose empty output looked identical to a
# successful one. A sibling installer copied from this one reported "cron
# installed" on a host where nothing had been installed. An installer that
# claims success it has not earned is the same silent failure as the job it
# installs, moved one level up.
echo
echo "== cron =="
if crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; then
  say "already present, leaving it alone"
else
  say "appending"
  {
    crontab -l 2>/dev/null || true
    echo "# USDA morning boxed beef cutout -> JSA.BOXED_BEEF.CUTOUT_AM (times are CT)"
    echo "$CRON_LINE"
    echo "$CRON_LINE2"
  } | crontab -
fi

# The verification, and it is not optional: count OUR lines in the crontab as
# it now reads. Two expected, and anything else is a failure to report, not a
# cosmetic difference.
installed=$(crontab -l 2>/dev/null | grep -cF "$CRON_TAG" || true)
if [ "$installed" -ne 2 ]; then
  echo
  echo "FAILED: expected 2 crontab lines matching '$CRON_TAG', found $installed." >&2
  echo "The crontab did not take. Nothing is scheduled; do not assume it is." >&2
  crontab -l 2>/dev/null | sed 's/^/    /' >&2 || echo "    (crontab unreadable)" >&2
  exit 1
fi
say "verified: $installed lines present"

mkdir -p "$DEST/logs"

echo
echo "== done =="
crontab -l | grep -B1 -A1 "$CRON_TAG" | sed 's/^/  /'
say "logs: $DEST/logs/am_cutout_*.log  (cron-alert mails on a non-zero exit)"
