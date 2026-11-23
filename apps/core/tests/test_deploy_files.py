"""The files for the server (phase 15) are checked as far as a Mac can: they parse, and they say what they must."""

import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

DEPLOY = Path(settings.BASE_DIR) / "deploy"
SCRIPTS = sorted(DEPLOY.glob("*.sh"))


def test_there_are_scripts_to_check():
    names = {p.name for p in SCRIPTS}
    assert {
        "check_programs.sh",
        "check_server.sh",
        "first_setup.sh",
        "manage.sh",
        "release.sh",
        "uptime_check.sh",
    } <= names


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_every_deploy_script_parses_and_can_be_run(script):
    done = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert script.stat().st_mode & 0o111, f"{script.name} is not executable"
    assert script.read_text().startswith("#!/usr/bin/env bash")


def test_the_crontab_watches_the_app_runs_the_jobs_daily_and_the_close_and_never_two_at_once():
    lines = [x for x in (DEPLOY / "crontab.txt").read_text().splitlines() if x and not x.startswith("#")]
    jobs = [x for x in lines if not x.startswith("MAILTO")]
    assert any(x.startswith("MAILTO=") for x in lines)
    text = "\n".join(jobs)
    assert "* * * * *   <site folder>/app/deploy/run_site.sh ensure" in text  # the watchdog, instead of systemd
    assert all("flock -n" in x for x in jobs if "run_site.sh" not in x)
    assert "run_jobs --max-seconds 55" in text
    assert "5 0 * * *" in text and " daily" in text
    assert "15 0 1 * *" in text and "close_period" in text
    assert "backup" not in text  # backups are the owner's own (Borg)


def test_nothing_in_the_deploy_files_needs_root_systemd_or_the_servers_settings():
    for path in list(DEPLOY.glob("*.sh")) + [DEPLOY / "htaccess_template", DEPLOY / "crontab.txt"]:
        code = "\n".join(x for x in path.read_text().splitlines() if not x.lstrip().startswith("#"))
        words = ["systemctl", "sudo ", "dnf ", "yum ", "apt "]
        if not path.name.startswith("check_"):  # the two check scripts only READ /etc/...-release
            words.append("/etc/")
        for word in words:
            assert word not in code, f"{path.name} uses {word!r}"
    assert not (DEPLOY / "unicorn.service").exists() and not (DEPLOY / "sudoers_unicorn").exists()


def test_the_htaccess_keeps_certificates_goes_to_https_serves_static_and_sends_the_rest_to_the_app():
    text = (DEPLOY / "htaccess_template").read_text()
    code = [x for x in text.splitlines() if x and not x.startswith("#")]
    body = "\n".join(code)
    order = [
        body.index("^\\.well-known/acme-challenge/"),
        body.index("%{HTTPS} off"),
        body.index("-f"),
        body.index("^static/"),
        body.index('RequestHeader set X-Forwarded-Proto "https"'),
        body.index("http://127.0.0.1:<PORT>/$1 [P,L]"),
    ]
    assert order == sorted(order)  # the exceptions come before the proxy rule
    assert "LimitRequestBody 12582912" in body


def test_the_apache_fallback_is_only_a_fallback_and_matches_the_htaccess():
    text = (DEPLOY / "apache_directives.conf").read_text()
    assert text.startswith("# FALLBACK ONLY")
    assert "ProxyPass /.well-known/acme-challenge/ !" in text and "ProxyPass /static/ !" in text
    assert 'RequestHeader set X-Forwarded-Proto "https"' in text and "http://127.0.0.1:<PORT>/" in text


def test_run_site_starts_watches_restarts_and_stops_one_site(tmp_path):
    """With a stand-in for gunicorn: ensure starts it once, is silent when it runs, restarts it after a crash."""
    import os
    import shutil
    import signal
    import time

    site = tmp_path / "site"
    (site / "app" / "deploy").mkdir(parents=True)
    (site / "venv" / "bin").mkdir(parents=True)
    shutil.copy(DEPLOY / "run_site.sh", site / "app" / "deploy" / "run_site.sh")
    (site / ".env").write_text("GUNICORN_PORT=18999\nGUNICORN_WORKERS=1\n")
    fake = site / "venv" / "bin" / "gunicorn"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'while [ $# -gt 0 ]; do case "$1" in --pid) PID="$2"; shift;; esac; shift; done\n'
        '( exec -a gunicorn-stand-in sleep 300 ) >/dev/null 2>&1 & echo $! > "$PID"\n'
    )
    for f in (fake, site / "app" / "deploy" / "run_site.sh"):
        f.chmod(0o755)
    script = str(site / "app" / "deploy" / "run_site.sh")

    def run(*args):
        return subprocess.run([script, *args], capture_output=True, text=True, timeout=60)

    pidfile = site / "run" / "gunicorn.pid"
    try:
        assert run("status").returncode == 1
        first = run("ensure")
        assert first.returncode == 0 and "starting" in first.stdout and run("status").returncode == 0
        pid = int(pidfile.read_text())
        assert run("ensure").stdout == ""  # all is well: silent, so cron sends no mail
        assert run("start").stdout.startswith("Already running")
        os.kill(pid, signal.SIGKILL)  # a crash
        time.sleep(0.3)
        assert run("status").returncode == 1
        assert "starting" in run("ensure").stdout and run("status").returncode == 0
        assert run("restart").returncode == 0 and int(pidfile.read_text()) != pid
        assert run("stop").stdout.strip() == "Stopped." and run("status").returncode == 1
        assert run("bogus").returncode == 2
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except OSError:
                pass


def test_run_site_refuses_without_a_port(tmp_path):
    import shutil

    site = tmp_path / "site"
    (site / "app" / "deploy").mkdir(parents=True)
    shutil.copy(DEPLOY / "run_site.sh", site / "app" / "deploy" / "run_site.sh")
    (site / ".env").write_text("SECRET_KEY=x\n")
    done = subprocess.run([str(site / "app" / "deploy" / "run_site.sh"), "status"], capture_output=True, text=True)
    assert done.returncode == 2 and "GUNICORN_PORT" in done.stderr


def test_the_release_script_checks_backs_up_migrates_restarts_and_rolls_back():
    text = (DEPLOY / "release.sh").read_text()
    order = [
        text.index(x) for x in ("before_release.sh", "git checkout --detach", "check --deploy", "migrate --noinput")
    ] + [text.rindex('run_site.sh" restart')]
    assert order == sorted(order)
    assert text.index("before_release.sh") < text.index("switched=1")  # nothing changes without a backup
    assert "BACKUP_DONE" in text
    assert "trap rollback ERR" in text and "git checkout --detach" in text and "rolled back" in text


def test_the_version_comes_from_the_environment_then_the_version_file(monkeypatch, tmp_path):
    import unicorn.settings as s

    monkeypatch.setattr(s, "BASE_DIR", tmp_path)
    monkeypatch.delenv("UNICORN_VERSION", raising=False)
    assert s._release_version() == "dev"
    (tmp_path / ".version").write_text("v0.9.0\n")
    assert s._release_version() == "v0.9.0"
    monkeypatch.setenv("UNICORN_VERSION", "v1.0.0")
    assert s._release_version() == "v1.0.0"


def test_the_env_example_names_every_production_variable():
    text = (Path(settings.BASE_DIR) / ".env.example").read_text()
    for name in (
        "SECRET_KEY",
        "UNICORN_MASTER_KEY",
        "UNICORN_HMAC_KEY",
        "ALLOWED_HOSTS",
        "SITE_URL",
        "DATABASE_URL",
        "EMAIL_URL",
        "DEFAULT_FROM_EMAIL",
        "ADMIN_EMAILS",
        "SECURITY_CONTACT",
        "ADMIN_PATH",
        "SOURCE_URL",
        "SECURE_HSTS_SECONDS",
        "STATIC_ROOT",
        "GUNICORN_PORT",
        "GUNICORN_WORKERS",
        "USE_X_FORWARDED_HOST",
        "PRIVATE_MEDIA_ROOT",
        "BACKUP_EXPECTED",
        "TEST_DATABASE_NAME",
    ):
        assert f"\n{name}=" in "\n" + text, name


def test_requirements_server_is_requirements_with_pymysql_instead_of_mysqlclient():
    root = Path(settings.BASE_DIR)

    def pins(name):
        return [x for x in (root / name).read_text().splitlines() if x and not x.startswith("#")]

    base, server = pins("requirements.txt"), pins("requirements-server.txt")
    assert [x for x in base if not x.startswith("mysqlclient")] == [x for x in server if not x.startswith("PyMySQL")]
    assert any(x.startswith("mysqlclient==") for x in base) and any(x.startswith("PyMySQL==") for x in server)
    assert not any(x.startswith("mysqlclient") for x in server)


def test_pymysql_stands_in_for_mysqlclient_when_that_is_missing():
    """A fresh Python without mysqlclient still gets a driver that Django accepts."""
    code = (
        "import sys; sys.modules['MySQLdb'] = None\n"
        "import unicorn, MySQLdb\n"
        "from django.db.backends.mysql import base\n"
        "print(MySQLdb.__name__, MySQLdb.version_info >= (2, 2, 1))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=settings.BASE_DIR)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["pymysql", "True"]
