#!/usr/bin/env bash
# Runs `manage.py` the way the server does: with the virtual server's .env and virtual environment.
# Used by cron and by operators:  ~/app/deploy/manage.sh check --deploy
set -euo pipefail
export UNICORN_ENV_FILE="${UNICORN_ENV_FILE:-$HOME/.env}"
cd "${APP_DIR:-$HOME/app}"
exec "${VENV_DIR:-$HOME/venv}/bin/python" manage.py "$@"
