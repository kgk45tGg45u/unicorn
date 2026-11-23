#!/usr/bin/env bash
# Looks at /healthz and emails the operators on the FIRST failure and when it recovers (P15.T08).
# Run from the SECOND machine every 5 minutes (cron), so that it still works when the box is down:
#
#   */5 * * * *  /home/<user>/uptime_check.sh https://unicorn.example.org operators@example.org
#
# It keeps its state in a small file; with `mail` from the system (mailx or the like). No outside company.
# The email says only which checks failed (the names /healthz gives), never more.
set -u

SITE="${1:?usage: uptime_check.sh <site url> <operators email> [state file]}"
TO="${2:?usage: uptime_check.sh <site url> <operators email> [state file]}"
STATE="${3:-$HOME/.uptime_state_$(printf '%s' "${SITE}" | tr -c 'A-Za-z0-9' '_')}"

body="$(curl -sS --max-time 20 "${SITE%/}/healthz" 2>&1)"
code=$?
# curl -f would hide the body, so look at the answer ourselves: "ok" means healthy.
if [ "${code}" = "0" ] && printf '%s' "${body}" | grep -q '"status": *"ok"'; then
  now="up"
else
  now="down"
fi
was="$(cat "${STATE}" 2>/dev/null || echo up)"

send() { printf '%s\n' "$2" | mail -s "$1" "${TO}"; }

if [ "${now}" = "down" ] && [ "${was}" = "up" ]; then
  detail="$(printf '%s' "${body}" | head -c 300)"
  send "Unicorn is not healthy: ${SITE}" "The health check of ${SITE} failed.
Answer: ${detail:-no answer (curl exit code ${code})}
Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
elif [ "${now}" = "up" ] && [ "${was}" = "down" ]; then
  send "Unicorn is healthy again: ${SITE}" "The health check of ${SITE} answers ok again.
Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
printf '%s' "${now}" > "${STATE}"
[ "${now}" = "up" ]
