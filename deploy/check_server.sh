#!/usr/bin/env bash
# Looks at the server and prints what it finds (P15.T01). It only reads: it changes nothing.
# Run it as the virtual server's user, or as root for a fuller picture:  bash deploy/check_server.sh
# The database is asked with the login in ~/.my.cnf (chmod 600); without it the database lines say so.
# Then write the answers in docs/deploy_log.md. Never paste passwords or keys there.
set -u

line() { printf '\n== %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
run() { "$@" 2>&1 || echo "(did not work: $*)"; }

line "Operating system"
if [ -r /etc/almalinux-release ]; then cat /etc/almalinux-release
elif [ -r /etc/os-release ]; then head -3 /etc/os-release
else uname -sr; fi

line "Database version"
if have mariadb; then run mariadb --version; elif have mysql; then run mysql --version; else echo "(no mariadb or mysql client found)"; fi

line "Database settings"
if have mariadb; then DB=mariadb; elif have mysql; then DB=mysql; else DB=""; fi
if [ -n "$DB" ]; then
  if [ -f "$HOME/.my.cnf" ] || [ "$(id -u)" = "0" ]; then
    run "$DB" -N -e "SELECT CONCAT('version: ', @@version);
                     SELECT CONCAT('log_bin: ', @@log_bin);
                     SELECT CONCAT('log_bin_trust_function_creators: ', @@log_bin_trust_function_creators);
                     SELECT CONCAT('character_set_server: ', @@character_set_server);
                     SELECT CONCAT('innodb_file_per_table: ', @@innodb_file_per_table);"
    echo "-- time zone tables (NULL means they are not loaded):"
    run "$DB" -N -e "SELECT CONVERT_TZ('2026-01-01 00:00:00','UTC','Europe/Berlin');"
  else
    echo "(no ~/.my.cnf: cannot ask the database)"
  fi
fi

line "Apache"
if have httpd; then
  run httpd -v
  modules="$(httpd -M 2>/dev/null || true)"
  for m in proxy_module proxy_http_module headers_module ssl_module; do
    if printf '%s' "$modules" | grep -q "${m}"; then echo "$m: yes"; else echo "$m: NO"; fi
  done
elif have apache2; then
  run apache2 -v
else
  echo "(httpd not found)"
fi

line "Python"
if have python3.12; then python3.12 --version; else echo "python3.12: NOT installed"; fi

line "SELinux"
if have getenforce; then getenforce; else echo "(getenforce not found)"; fi

line "Time"
if have timedatectl; then timedatectl 2>&1 | grep -E "Local time|Time zone|synchronized|NTP" || timedatectl; else date; fi

line "Space and memory"
df -h /home 2>&1 | head -3
if have free; then free -m; fi
if have nproc; then echo "processors: $(nproc)"; fi

echo
echo "Done. Nothing was changed."
