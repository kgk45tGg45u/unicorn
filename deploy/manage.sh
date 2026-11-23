#!/usr/bin/env bash
# Runs `manage.py` the way the server does: with the site's .env and virtual environment (P15.T04).
# Used by cron and by operators:  <site folder>/app/deploy/manage.sh check --deploy
# The site folder is found from where this script lies: <site folder>/app/deploy/manage.sh. It holds app/, venv/,
# .env, run/ and private_media/ (SITE_ROOT overrides it). Staging and production can share one Unix user.
set -euo pipefail
ROOT="${SITE_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
export UNICORN_ENV_FILE="${UNICORN_ENV_FILE:-${ROOT}/.env}"
cd "${ROOT}/app"
exec "${ROOT}/venv/bin/python" manage.py "$@"
