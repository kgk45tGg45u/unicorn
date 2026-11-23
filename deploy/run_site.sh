#!/usr/bin/env bash
# Starts, stops and watches the web app of ONE Unicorn site, as the site's own user. No systemd, no root.
#
#   run_site.sh ensure    start it if it is not running (this is the line for cron, every minute: silent when all is well)
#   run_site.sh start | stop | restart | status
#
# The site's folder is found from where this script lies: <site folder>/app/deploy/run_site.sh. The site folder
# holds app/, venv/, .env, run/ and private_media/. So staging and production can live side by side under one user.
# The port and the number of workers come from the site's .env (GUNICORN_PORT, GUNICORN_WORKERS).
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${UNICORN_ENV_FILE:-${ROOT}/.env}"
RUN="${ROOT}/run"
PIDFILE="${RUN}/gunicorn.pid"
LOG="${RUN}/gunicorn.log"
MAX_LOG_BYTES=$((10 * 1024 * 1024))

[ -f "${ENV_FILE}" ] || { echo "No ${ENV_FILE}" >&2; exit 2; }
setting() { grep -E "^$1=" "${ENV_FILE}" | tail -1 | cut -d= -f2- | tr -d '"' || true; }
PORT="$(setting GUNICORN_PORT)"
WORKERS="$(setting GUNICORN_WORKERS)"; WORKERS="${WORKERS:-2}"
[[ "${PORT}" =~ ^[0-9]+$ ]] || { echo "GUNICORN_PORT is not set in ${ENV_FILE}" >&2; exit 2; }

running() {
  [ -f "${PIDFILE}" ] || return 1
  local pid; pid="$(cat "${PIDFILE}" 2>/dev/null)"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null && ps -p "${pid}" -o args= 2>/dev/null | grep -q gunicorn
}

start() {
  if running; then echo "Already running (process $(cat "${PIDFILE}"))."; return 0; fi
  mkdir -p "${RUN}"
  if [ -f "${LOG}" ] && [ "$(wc -c < "${LOG}")" -gt "${MAX_LOG_BYTES}" ]; then mv -f "${LOG}" "${LOG}.1"; fi
  rm -f "${PIDFILE}"
  cd "${ROOT}/app" || exit 2
  UNICORN_ENV_FILE="${ENV_FILE}" PYTHONUNBUFFERED=1 "${ROOT}/venv/bin/gunicorn" unicorn.wsgi:application \
    --bind "127.0.0.1:${PORT}" --workers "${WORKERS}" --timeout 60 \
    --max-requests 1000 --max-requests-jitter 100 \
    --daemon --pid "${PIDFILE}" --capture-output --error-logfile "${LOG}" --log-level warning
  # gunicorn forks away; give it a moment to either come up or fail
  for _ in 1 2 3 4 5 6 7 8 9 10; do sleep 0.5; running && { echo "Started on 127.0.0.1:${PORT}."; return 0; }; done
  echo "Did not start. Last lines of ${LOG}:" >&2
  tail -n 15 "${LOG}" >&2 2>/dev/null
  return 1
}

stop() {
  running || { echo "Not running."; rm -f "${PIDFILE}"; return 0; }
  local pid; pid="$(cat "${PIDFILE}")"
  kill -TERM "${pid}"                      # graceful: finishes the requests it is serving
  for _ in $(seq 1 40); do sleep 0.5; running || { echo "Stopped."; return 0; }; done
  kill -KILL "${pid}" 2>/dev/null; rm -f "${PIDFILE}"; echo "Stopped (it had to be forced)."
}

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  if running; then echo "Running (process $(cat "${PIDFILE}")) on 127.0.0.1:${PORT}."; else echo "Not running."; exit 1; fi ;;
  ensure)  running || { echo "$(date '+%F %T') not running, starting"; start; } ;;
  *) echo "Usage: run_site.sh ensure|start|stop|restart|status" >&2; exit 2 ;;
esac
