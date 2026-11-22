import pytest
from django.db import connection


@pytest.mark.django_db
def test_database_is_mysql_family():
    assert connection.vendor == "mysql"
    with connection.cursor() as c:
        c.execute("SELECT @@character_set_database")
        assert c.fetchone()[0] == "utf8mb4"


@pytest.mark.django_db
def test_time_zone_tables_loaded():
    with connection.cursor() as c:
        c.execute("SELECT CONVERT_TZ('2026-01-01 00:00:00', 'UTC', 'Europe/Berlin')")
        assert c.fetchone()[0] is not None
