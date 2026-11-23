#!/usr/bin/env bash
# Which programs does Unicorn need, and which are on this box? Reads only. Installs and changes nothing.
# Run it as the virtual server's user (or root) and send the whole output back.
set -u
export LC_ALL=C

show() {  # show <label> <what it is for> <command> [version command]
  local label="$1" use="$2" cmd="$3" ver="${4:-}" path v=""
  path="$(command -v "$cmd" 2>/dev/null || true)"
  if [ -n "$path" ]; then
    [ -n "$ver" ] && v="$(eval "$ver" 2>&1 | head -1)"
    printf 'FOUND    %-22s %s  [%s]\n' "$label" "$v" "$use"
  else
    printf 'MISSING  %-22s [%s]\n' "$label" "$use"
  fi
}

echo "== Box"
cat /etc/almalinux-release 2>/dev/null || head -2 /etc/os-release 2>/dev/null || uname -sr
echo "user: $(id -un)"

echo; echo "== To run the app"
show "python3.12"       "runs Unicorn"                       python3.12 "python3.12 --version"
if command -v python3.12 >/dev/null 2>&1; then
  python3.12 -c "import venv, ensurepip" 2>/dev/null && echo "FOUND    python3.12 venv+pip     [own folder for Unicorn's libraries]" || echo "MISSING  python3.12 venv+pip     [own folder for Unicorn's libraries]"
fi
show "other python3"    "only if there is no 3.12"           python3 "python3 --version"
show "git"              "gets the code and the version tags" git "git --version"
show "curl"             "health check, release script"       curl "curl --version"

echo; echo "== To build the database driver (mysqlclient). Without them the pure-Python PyMySQL is the fallback"
show "gcc"              "compiler"                           gcc "gcc --version"
show "pkg-config"       "finds the database library"         pkg-config "pkg-config --version"
for c in mariadb_config mysql_config; do show "$c" "database library settings" "$c" "$c --version"; done
if command -v pkg-config >/dev/null 2>&1; then
  for m in mariadb libmariadb mysqlclient; do pkg-config --exists "$m" 2>/dev/null && echo "FOUND    pkg-config $m        [database library headers]"; done
fi
ls /usr/include/mysql/mysql.h /usr/include/mariadb/mysql.h 2>/dev/null | sed 's/^/FOUND    header                 /' ; true

echo; echo "== Database"
show "mariadb client"   "database tools"                     mariadb "mariadb --version"
show "mysql client"     "older name of the same"             mysql "mysql --version"
show "mariadb-dump"     "backup of the database"             mariadb-dump "mariadb-dump --version"
show "mysqldump"        "older name of the same"             mysqldump "mysqldump --version"
show "mariadb-tzinfo-to-sql" "loads time zone tables, once"  mariadb-tzinfo-to-sql
show "mysql_tzinfo_to_sql"   "older name of the same"        mysql_tzinfo_to_sql

echo; echo "== Web server and tools"
show "httpd"            "Apache"                             httpd "httpd -v"
if command -v httpd >/dev/null 2>&1; then
  mods="$(httpd -M 2>/dev/null || true)"
  for m in proxy_module proxy_http_module headers_module ssl_module; do
    printf '%s' "$mods" | grep -q "$m" && echo "FOUND    apache $m" || echo "MISSING  apache $m"
  done
fi
show "ss"               "finds a free port for the web app"  ss "ss --version"
show "crontab"          "cron jobs"                          crontab
show "flock"            "one cron job at a time"             flock "flock --version"

echo; echo "== Mail (login codes, error mails)"
for m in sendmail postfix mail mailx; do show "$m" "email" "$m"; done

echo; echo "== Backups"
show "borg"             "your backups"        borg "borg --version"
show "rsync"            "copy to a second machine"           rsync "rsync --version"
show "ssh"              "copy to a second machine"           ssh "ssh -V"
show "tar"              "packs files"                        tar "tar --version"
show "gzip"             "compresses"                         gzip "gzip --version"

echo; echo "== Settings that matter"
command -v getenforce >/dev/null 2>&1 && echo "SELinux: $(getenforce)"
command -v timedatectl >/dev/null 2>&1 && timedatectl 2>/dev/null | grep -E "Time zone|synchronized"
df -h "$HOME" 2>/dev/null | tail -1 | awk '{print "free space in home: " $4}'

echo; echo "Done. Nothing was installed or changed."
