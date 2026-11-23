"""The files for the server (phase 15) are checked as far as a Mac can: they parse, and they say what they must."""

import subprocess
from pathlib import Path

import pytest
from django.conf import settings

DEPLOY = Path(settings.BASE_DIR) / "deploy"
SCRIPTS = sorted(DEPLOY.glob("*.sh"))


def test_there_are_scripts_to_check():
    names = {p.name for p in SCRIPTS}
    assert {"backup.sh", "check_server.sh", "first_setup.sh", "manage.sh", "release.sh", "uptime_check.sh"} <= names


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_every_deploy_script_parses_and_can_be_run(script):
    done = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert script.stat().st_mode & 0o111, f"{script.name} is not executable"
    assert script.read_text().startswith("#!/usr/bin/env bash")


def test_the_crontab_runs_the_jobs_daily_and_the_close_and_never_two_at_once():
    lines = [x for x in (DEPLOY / "crontab.txt").read_text().splitlines() if x and not x.startswith("#")]
    jobs = [x for x in lines if not x.startswith("MAILTO")]
    assert any(x.startswith("MAILTO=") for x in lines)
    assert all("flock -n" in x for x in jobs)
    text = "\n".join(jobs)
    assert "* * * * *" in text and "run_jobs --max-seconds 55" in text
    assert "5 0 * * *" in text and " daily" in text
    assert "15 0 1 * *" in text and "close_period" in text
    assert "30 2 * * *" in text and "backup.sh" in text


def test_the_service_runs_as_the_site_user_with_gunicorn_and_the_env_file():
    unit = (DEPLOY / "unicorn.service").read_text()
    assert "User=<user>" in unit and "gunicorn unicorn.wsgi:application" in unit
    assert "--bind 127.0.0.1:8001" in unit and "UNICORN_ENV_FILE=/home/<user>/.env" in unit
    assert "NoNewPrivileges=true" in unit and "Restart=on-failure" in unit


def test_the_sudoers_line_lets_the_user_only_restart_and_look_at_the_service():
    lines = [x for x in (DEPLOY / "sudoers_unicorn").read_text().splitlines() if x and not x.startswith("#")]
    assert len(lines) == 1
    allowed = lines[0].split("NOPASSWD:")[1]
    assert {c.strip() for c in allowed.split(",")} == {
        "/usr/bin/systemctl restart unicorn.service",
        "/usr/bin/systemctl status unicorn.service",
    }
    assert "ALL\n" not in lines[0].split("NOPASSWD:")[1]


def test_apache_keeps_the_certificate_renewals_and_static_files_and_says_it_is_https():
    text = (DEPLOY / "apache_directives.conf").read_text()
    assert "ProxyPass /.well-known/acme-challenge/ !" in text and "ProxyPass /static/ !" in text
    assert 'RequestHeader set X-Forwarded-Proto "https"' in text
    assert "ProxyPass / http://127.0.0.1:8001/" in text
    assert "LimitRequestBody 12582912" in text


def test_the_release_script_checks_backs_up_migrates_restarts_and_rolls_back():
    text = (DEPLOY / "release.sh").read_text()
    order = [text.index(x) for x in ("backup.sh", "check --deploy", "migrate --noinput")] + [
        text.rindex("systemctl restart")
    ]
    assert order == sorted(order)
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
        "PRIVATE_MEDIA_ROOT",
        "BACKUP_EXPECTED",
        "TEST_DATABASE_NAME",
    ):
        assert f"\n{name}=" in "\n" + text, name
