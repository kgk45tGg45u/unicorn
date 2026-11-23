# Deploy log

Every step done on a server, with its date and anything unexpected. **Never write a password, a key or a token here.** Add a line at the bottom of the right section each time. If a step was not done yet, it stays as it is.

## State of the steps (phase 15)

| Step | Who | Done on staging | Done on production |
|---|---|---|---|
| T01 `deploy/check_server.sh` run, answers written below | operator | not yet | not yet |
| T02 packages installed (root) | operator with root | not yet | not yet |
| T03 virtual servers, DNS, certificates, databases, time zone tables (root) | operator with root | not yet | not yet |
| T04 code, `~/.env`, `first_setup.sh` | operator | not yet | not yet |
| T05 gunicorn service, sudoers line, Apache directives (root) | operator with root | not yet | not yet |
| T06 first release through `release.sh` | operator | not yet | not yet |
| T07 cron, email (DKIM, SPF, DMARC); first restore test of the owner's Borg backup | operator | not yet | not yet |
| T08 uptime check from the second machine | operator | not yet | not yet |
| T09 `launch_check` shows no FAIL; the founders' meeting | founders | not yet | not yet |

## T01 — What the server answered

Run `bash deploy/check_server.sh` on the box and copy the lines here (the answers only: no names, no secrets). Then fill in "What it means".

| Check | Answer | Needed | If not |
|---|---|---|---|
| AlmaLinux | | 8.10 or 9.x | ask the owner (docs/12) |
| MariaDB | | 10.6 or newer (10.11 or 11.4 recommended) | 10.5 still works: Django 5.2 supports it, and the job runner falls back without "skip locked" (P00.T06). Upgrading to 10.11 is an owner decision, after a full backup (docs/12) |
| `log_bin` and `log_bin_trust_function_creators` | | if `log_bin` is ON, trust must be 1 | T03 step 4 |
| Character set | | `utf8mb4` | T03 step 4 |
| Time zone tables | | not NULL | T03 step 5 |
| Apache modules (`proxy`, `proxy_http`, `headers`, `ssl`) | | all four yes | `dnf install mod_ssl`; the proxy and headers modules come with `httpd` |
| Python 3.12 | | installed | T02 |
| SELinux | | `Disabled` or `Permissive`, or `Enforcing` with T03 step 6 | T03 step 6 |
| Clock | | synchronised, time zone `Europe/Berlin` (or the cron lines are shifted, P15.T07) | `timedatectl set-timezone Europe/Berlin` |
| Free space in `/home` | | at least 10 GB | ask the owner |
| Location of the box | | in the EU/EEA (the owner answers) | open question in docs/12 |

**What T02 and T03 must change:** *(write the list here after the check)*

## Steps taken

*(One line each: date, who, what, anything unexpected.)*
