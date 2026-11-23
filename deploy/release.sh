#!/usr/bin/env bash
# Puts a tagged version of Unicorn on this virtual server (P15.T06). Run as the virtual server's user.
#
#   deploy/release.sh v0.9.0                      production (service unicorn.service)
#   deploy/release.sh v0.9.0 unicorn-staging.service   staging
#
# Always staging first. If anything fails after the code was switched, the old version is put back and the
# service restarted. The database stays migrated; that is safe because every migration lets the previous
# release still run (CLAUDE.md, "Database").
#
# Environment (all optional): APP_DIR, VENV_DIR, UNICORN_ENV_FILE, HEALTH_URL (to test the rollback, point it at
# an address that fails), HEALTH_WAIT (seconds to wait before looking, default 5).
set -euo pipefail

TAG="${1:-}"
SERVICE="${2:-unicorn.service}"
[[ "${TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Usage: release.sh vX.Y.Z [service]" >&2; exit 2; }

APP_DIR="${APP_DIR:-$HOME/app}"
VENV_DIR="${VENV_DIR:-$HOME/venv}"
export UNICORN_ENV_FILE="${UNICORN_ENV_FILE:-$HOME/.env}"
HERE="$(cd "$(dirname "$0")" && pwd)"
MANAGE="${HERE}/manage.sh"
cd "${APP_DIR}"

SITE_URL="$(grep -E '^SITE_URL=' "${UNICORN_ENV_FILE}" | tail -1 | cut -d= -f2- || true)"
HEALTH_URL="${HEALTH_URL:-${SITE_URL%/}/healthz}"
[[ "${HEALTH_URL}" == http* ]] || { echo "No SITE_URL in ${UNICORN_ENV_FILE}, and no HEALTH_URL given." >&2; exit 2; }

# 1. Remember what runs now.
PREVIOUS="$(cat .version 2>/dev/null || true)"
[ -n "${PREVIOUS}" ] || PREVIOUS="$(git describe --tags --exact-match 2>/dev/null || git rev-parse HEAD)"
echo "Now running: ${PREVIOUS}. Going to: ${TAG}."

switched=0
rollback() {
  trap - ERR
  echo "Something went wrong; putting ${PREVIOUS} back." >&2
  if [ "${switched}" = "1" ]; then
    git checkout --detach "${PREVIOUS}" >/dev/null 2>&1 || true
    echo "${PREVIOUS}" > .version
    "${VENV_DIR}/bin/pip" install -q -r requirements.txt || true
    sudo /usr/bin/systemctl restart "${SERVICE}" || true
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
"${VENV_DIR}/bin/pip" install -q -r requirements.txt

# 4. A fresh backup before any migration.
"${HERE}/backup.sh"

# 5. Checks, migrations, static files.
"${MANAGE}" check --deploy
"${MANAGE}" migrate --noinput
"${MANAGE}" createcachetable
"${MANAGE}" collectstatic --noinput

# 6. Restart.
sudo /usr/bin/systemctl restart "${SERVICE}"

# 7. Look at /healthz.
sleep "${HEALTH_WAIT:-5}"
if ! curl -fsS --max-time 20 "${HEALTH_URL}" >/dev/null; then
  echo "/healthz did not answer well at ${HEALTH_URL}." >&2
  rollback
fi

echo "Released ${TAG}. Now write it in docs/deploy_log.md."
