#!/usr/bin/env bash
# The monthly restore test (docs/08 section 6, P14.T09). Run on the STAGING server by an operator who sends the
# private backup key through standard input, so that it never touches the disk:
#
#   ssh staging '~/app/deploy/restore_test.sh /path/unicorn-2027-03-01.tar.age' < ~/keys/unicorn-backup.key
#
# Staging never holds the production master key, so personal fields stay unreadable there.
set -uo pipefail

BACKUP_FILE="${1:-}"
APP_DIR="${APP_DIR:-${HOME}/app}"
PY="${PY:-${APP_DIR}/.venv/bin/python}"
STAGING_USER="${STAGING_USER:-$(whoami)}"
RESTORE_DB="${RESTORE_DB:-${STAGING_USER}_restore}"
REASONS=()

say_fail() { REASONS+=("$1"); }
finish() {
  if [ "${#REASONS[@]}" -eq 0 ]; then
    echo "RESTORE TEST OK"
    exit 0
  fi
  echo "RESTORE TEST FAILED"
  for r in "${REASONS[@]}"; do echo " - ${r}"; done
  exit 1
}

[ -n "${BACKUP_FILE}" ] && [ -f "${BACKUP_FILE}" ] || { say_fail "no backup file was given or it does not exist"; finish; }
command -v age >/dev/null 2>&1 || { say_fail "age is not installed"; finish; }

if command -v mariadb >/dev/null 2>&1; then SQL=mariadb; else SQL=mysql; fi
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"; ${SQL} -e "DROP DATABASE IF EXISTS \`${RESTORE_DB}\`" >/dev/null 2>&1 || true' EXIT

# 1. decrypt: the private key arrives on standard input and is never written to a file
if ! age -d -i - "${BACKUP_FILE}" 2>"${WORK}/age.err" | tar -C "${WORK}" -xf -; then
  say_fail "the backup could not be decrypted: $(head -c 200 "${WORK}/age.err")"
  finish
fi
[ -f "${WORK}/database.sql.gz" ] || { say_fail "the backup has no database dump"; finish; }

# 2. load the dump into the restore database
${SQL} -e "DROP DATABASE IF EXISTS \`${RESTORE_DB}\`; CREATE DATABASE \`${RESTORE_DB}\` CHARACTER SET utf8mb4;" \
  || { say_fail "the restore database could not be created"; finish; }
if ! gunzip -c "${WORK}/database.sql.gz" | ${SQL} "${RESTORE_DB}"; then
  say_fail "the dump could not be loaded"
  finish
fi

# The app reads the same settings as staging, but its database is the restored copy.
RESTORE_ENV=(env "DATABASE_NAME_OVERRIDE=${RESTORE_DB}")

# 3. check the books of the restored database from the start
if ! "${RESTORE_ENV[@]}" "${PY}" "${APP_DIR}/manage.py" audit_books --full >"${WORK}/audit.txt" 2>&1; then
  say_fail "the books of the restored database failed the audit: $(tail -n 3 "${WORK}/audit.txt" | tr '\n' ' ')"
fi

# 4. compare the chain heads with the fingerprints published on that day
PUBLISHED_ARGS=()
[ -n "${PUBLISHED_FINGERPRINTS:-}" ] && [ -f "${PUBLISHED_FINGERPRINTS}" ] && PUBLISHED_ARGS=(--published "${PUBLISHED_FINGERPRINTS}")
if ! "${RESTORE_ENV[@]}" "${PY}" "${APP_DIR}/manage.py" compare_fingerprints "${PUBLISHED_ARGS[@]}" >"${WORK}/fp.txt" 2>&1; then
  say_fail "the chain heads do not match the published fingerprints: $(tail -n 3 "${WORK}/fp.txt" | tr '\n' ' ')"
fi

# 5. do the deletions again, as after any restore (P14.T04)
if ! "${RESTORE_ENV[@]}" "${PY}" "${APP_DIR}/manage.py" reapply_deletions >"${WORK}/del.txt" 2>&1; then
  say_fail "reapply_deletions failed: $(tail -n 3 "${WORK}/del.txt" | tr '\n' ' ')"
fi

# 6. the trap drops the restore database; 7. print the result
finish
