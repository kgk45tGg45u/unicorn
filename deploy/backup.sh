#!/usr/bin/env bash
# Nightly backup of Unicorn (docs/08 section 6, P14.T09). Run as the virtual server's user from cron (P15.T07).
#
# What it does:
#   1. dumps the database (the password is read from ~/.my.cnf, never from the command line);
#   2. packs the private files (~/private_media);
#   3. compresses and encrypts both to the backup PUBLIC key in ~/backup_recipient.txt (the private key is never here);
#   4. writes ~/backups/unicorn-<date>.tar.age and a checksum file;
#   5. copies them to the second machine (BACKUP_TARGET in ~/.backup.env);
#   6. keeps 30 daily and 12 monthly copies, here and there, and deletes older ones;
#   7. writes the time of success to ~/run/last_backup, which /healthz reads.
set -euo pipefail

HOME_DIR="${HOME}"
APP_ENV="${HOME_DIR}/.backup.env"
DB_NAME="${DB_NAME:-}"
BACKUP_DIR="${BACKUP_DIR:-${HOME_DIR}/backups}"
PRIVATE_DIR="${PRIVATE_DIR:-${HOME_DIR}/private_media}"
RECIPIENT_FILE="${RECIPIENT_FILE:-${HOME_DIR}/backup_recipient.txt}"
RUN_DIR="${RUN_DIR:-${HOME_DIR}/run}"
DAILY_KEEP="${DAILY_KEEP:-30}"
MONTHLY_KEEP="${MONTHLY_KEEP:-12}"

# shellcheck disable=SC1090
[ -f "${APP_ENV}" ] && . "${APP_ENV}"   # BACKUP_TARGET=user@host:/path, DB_NAME=...

fail() { echo "BACKUP FAILED: $*" >&2; exit 1; }

[ -n "${DB_NAME}" ] || fail "DB_NAME is not set (put it in ~/.backup.env)"
[ -f "${RECIPIENT_FILE}" ] || fail "no backup public key at ${RECIPIENT_FILE}"
[ -f "${HOME_DIR}/.my.cnf" ] || fail "no ~/.my.cnf with the database password (chmod 600)"

# Locally on a Mac, mysqldump takes the place of mariadb-dump: use whichever exists.
if command -v mariadb-dump >/dev/null 2>&1; then DUMP=mariadb-dump
elif command -v mysqldump >/dev/null 2>&1; then DUMP=mysqldump
else fail "neither mariadb-dump nor mysqldump is installed"; fi

# age is preferred; gpg works the same way with a public key.
if command -v age >/dev/null 2>&1; then
  encrypt() { age -R "${RECIPIENT_FILE}"; }
elif command -v gpg >/dev/null 2>&1; then
  encrypt() { gpg --batch --yes --encrypt --recipient-file "${RECIPIENT_FILE}"; }
else
  fail "neither age nor gpg is installed"
fi

umask 077
mkdir -p "${BACKUP_DIR}" "${RUN_DIR}"
DAY="$(date +%Y-%m-%d)"
WORK="$(mktemp -d "${BACKUP_DIR}/work.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

"${DUMP}" --single-transaction --routines --triggers --hex-blob --default-character-set=utf8mb4 \
  "${DB_NAME}" | gzip -9 > "${WORK}/database.sql.gz"

if [ -d "${PRIVATE_DIR}" ]; then
  tar -C "$(dirname "${PRIVATE_DIR}")" -czf "${WORK}/private_media.tar.gz" "$(basename "${PRIVATE_DIR}")"
else
  tar -czf "${WORK}/private_media.tar.gz" --files-from /dev/null
fi

# One archive of both parts, then encrypted. The listing inside is plain so the restore test can check it.
tar -C "${WORK}" -cf - database.sql.gz private_media.tar.gz | encrypt > "${BACKUP_DIR}/unicorn-${DAY}.tar.age"
( cd "${BACKUP_DIR}" && sha256sum "unicorn-${DAY}.tar.age" > "unicorn-${DAY}.tar.age.sha256" 2>/dev/null \
  || shasum -a 256 "unicorn-${DAY}.tar.age" > "unicorn-${DAY}.tar.age.sha256" )

# Keep 30 daily copies, plus the copy of the 1st of each month for 12 months.
prune() {
  local dir="$1"
  ls -1 "${dir}"/unicorn-*.tar.age 2>/dev/null | sort > "${WORK}/all.txt" || true
  local keep="${WORK}/keep.txt"
  : > "${keep}"
  tail -n "${DAILY_KEEP}" "${WORK}/all.txt" >> "${keep}"
  grep -E 'unicorn-[0-9]{4}-[0-9]{2}-01\.tar\.age$' "${WORK}/all.txt" | tail -n "${MONTHLY_KEEP}" >> "${keep}" || true
  sort -u "${keep}" -o "${keep}"
  while read -r file; do
    grep -qxF "${file}" "${keep}" || rm -f "${file}" "${file}.sha256"
  done < "${WORK}/all.txt"
}
prune "${BACKUP_DIR}"

if [ -n "${BACKUP_TARGET:-}" ]; then
  rsync -e "ssh -o BatchMode=yes" -a "${BACKUP_DIR}/unicorn-${DAY}.tar.age" "${BACKUP_DIR}/unicorn-${DAY}.tar.age.sha256" \
    "${BACKUP_TARGET}/" || fail "could not copy to the second machine"
  # The same pruning on the second machine: it lists and removes only files named unicorn-*.tar.age.
  REMOTE_HOST="${BACKUP_TARGET%%:*}"
  REMOTE_PATH="${BACKUP_TARGET#*:}"
  ssh -o BatchMode=yes "${REMOTE_HOST}" "cd '${REMOTE_PATH}' && \
    ls -1 unicorn-*.tar.age | sort > /tmp/unicorn-all.txt && \
    { tail -n ${DAILY_KEEP} /tmp/unicorn-all.txt; grep -E 'unicorn-[0-9]{4}-[0-9]{2}-01\\.tar\\.age\$' /tmp/unicorn-all.txt | tail -n ${MONTHLY_KEEP}; } | sort -u > /tmp/unicorn-keep.txt && \
    for f in \$(cat /tmp/unicorn-all.txt); do grep -qxF \"\$f\" /tmp/unicorn-keep.txt || rm -f \"\$f\" \"\$f.sha256\"; done; \
    rm -f /tmp/unicorn-all.txt /tmp/unicorn-keep.txt" || fail "could not clean the second machine"
fi

date -u +%Y-%m-%dT%H:%M:%SZ > "${RUN_DIR}/last_backup"
echo "backup ok: ${BACKUP_DIR}/unicorn-${DAY}.tar.age"
