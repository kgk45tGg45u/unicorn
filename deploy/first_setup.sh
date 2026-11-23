#!/usr/bin/env bash
# Run ONCE per virtual server, after the code, the virtual environment and ~/.env are in place (P15.T04).
# It makes the tables, the cache table and the static files, loads the contracts and the democratic defaults,
# and checks the settings. On later releases do NOT run it again: release.sh does what a release needs, and
# parameters then change only through tickets (P07.T05).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MANAGE="${HERE}/manage.sh"

[ -f "${UNICORN_ENV_FILE:-$HOME/.env}" ] || { echo "No .env file: copy .env.example to ~/.env and fill it in." >&2; exit 1; }

"${MANAGE}" migrate --noinput
"${MANAGE}" createcachetable
"${MANAGE}" loaddata contracts
"${MANAGE}" collectstatic --noinput
"${MANAGE}" load_defaults
"${MANAGE}" check --deploy
echo "First setup done."
