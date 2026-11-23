#!/usr/bin/env bash
# Puts a tagged version of Unicorn on one site (P15.T06). Run as the site's user, from the site's own copy:
#
#   <site folder>/app/deploy/release.sh v0.9.0
#
# The site folder is found from where this script lies. Always staging first. If anything fails after the code was switched, the old version is put back and the
# service restarted. The database stays migrated; that is safe because every migration lets the previous
# release still run (CLAUDE.md, "Database").
#
# Backups are the owner's own (Borg). Before anything is changed this script wants to know that a fresh one exists:
#   - if <site folder>/before_release.sh exists and can be run, it is run first (put your Borg command in it; if it fails,
#     nothing is released);
#   - otherwise make the backup yourself, and run this script again with BACKUP_DONE=1.
#
# Environment (all optional): SITE_ROOT, UNICORN_ENV_FILE, BACKUP_DONE, HEALTH_URL (to test the rollback,
# point it at an address that fails), HEALTH_WAIT (seconds to wait before looking, default 5).
# In the site's .env you may set REQUIREMENTS_FILE=requirements-server.txt (the list with PyMySQL, for a box without the
# database development files).
set -euo pipefail

TAG="${1:-}"
[[ "${TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Usage: release.sh vX.Y.Z" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${SITE_ROOT:-$(cd "${HERE}/../.." && pwd)}"
APP_DIR="${ROOT}/app"
VENV_DIR="${ROOT}/venv"
export UNICORN_ENV_FILE="${UNICORN_ENV_FILE:-${ROOT}/.env}"
export SITE_ROOT="${ROOT}"
MANAGE="${HERE}/manage.sh"
cd "${APP_DIR}"

SITE_URL="$(grep -E '^SITE_URL=' "${UNICORN_ENV_FILE}" | tail -1 | cut -d= -f2- || true)"
REQUIREMENTS_FILE="$(grep -E '^REQUIREMENTS_FILE=' "${UNICORN_ENV_FILE}" | tail -1 | cut -d= -f2- || true)"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-requirements.txt}"
HEALTH_URL="${HEALTH_URL:-${SITE_URL%/}/healthz}"
[[ "${HEALTH_URL}" == http* ]] || { echo "No SITE_URL in ${UNICORN_ENV_FILE}, and no HEALTH_URL given." >&2; exit 2; }

# 1. Remember what runs now.
PREVIOUS="$(cat .version 2>/dev/null || true)"
[ -n "${PREVIOUS}" ] || PREVIOUS="$(git describe --tags --exact-match 2>/dev/null || git rev-parse HEAD)"
echo "Now running: ${PREVIOUS}. Going to: ${TAG}."

# 1b. A fresh backup before anything changes (the owner's own: Borg).
if [ -x "${ROOT}/before_release.sh" ]; then
  echo "Running ${ROOT}/before_release.sh (your backup)."
  "${ROOT}/before_release.sh" || { echo "Your backup step failed. Nothing was changed." >&2; exit 3; }
elif [ "${BACKUP_DONE:-}" = "1" ]; then
  echo "Backup: you said it is done."
else
  echo "Make your backup first (Borg), then run this again with BACKUP_DONE=1." >&2
  echo "(Or make ${ROOT}/before_release.sh run it for you.) Nothing was changed." >&2
  exit 3
fi

switched=0
rollback() {
  trap - ERR
  echo "Something went wrong; putting ${PREVIOUS} back." >&2
  if [ "${switched}" = "1" ]; then
    git checkout --detach "${PREVIOUS}" >/dev/null 2>&1 || true
    echo "${PREVIOUS}" > .version
    "${VENV_DIR}/bin/pip" install -q -r "${REQUIREMENTS_FILE}" || true
    "${HERE}/run_site.sh" restart || true
  fi
  echo "Release failed, rolled back to ${PREVIOUS}" >&2
  exit 1
}
trap rollback ERR

# 2. Switch the code.
git fetch --tags --quiet
git checkout --detach "${TAG}" >/dev/null 2>&1
switched=1
echo "${TAG}" > .version

# 3. Packages.
"${VENV_DIR}/bin/pip" install -q -r "${REQUIREMENTS_FILE}"

# 4. Checks, migrations, static files.
"${MANAGE}" check --deploy
"${MANAGE}" migrate --noinput
"${MANAGE}" createcachetable
"${MANAGE}" collectstatic --noinput

# 5. Restart.
"${HERE}/run_site.sh" restart

# 6. Look at /healthz.
sleep "${HEALTH_WAIT:-5}"
if ! curl -fsS --max-time 20 "${HEALTH_URL}" >/dev/null; then
  echo "/healthz did not answer well at ${HEALTH_URL}." >&2
  rollback
fi

echo "Released ${TAG}. Now write it in docs/deploy_log.md."
