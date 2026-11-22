"""Raw SQL lives only here and in the trigger migrations (CLAUDE.md, "Database").

Both statements work on MySQL 8 and MariaDB 10.6+.
"""

from django.db import connection


def append_only_statements(table: str) -> list[str]:
    return [
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
        f"FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'append-only table'",
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
        f"FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'append-only table'",
    ]


def drop_statements(table: str) -> list[str]:
    return [f"DROP TRIGGER IF EXISTS {table}_no_update", f"DROP TRIGGER IF EXISTS {table}_no_delete"]


def triggers_present(tables, using=None) -> dict[str, bool]:
    """For each table: are both append-only triggers there?"""
    conn = connection if using is None else using
    with conn.cursor() as cursor:
        cursor.execute("SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()")
        names = {row[0] for row in cursor.fetchall()}
    return {t: {f"{t}_no_update", f"{t}_no_delete"} <= names for t in tables}


def install_append_only_triggers(schema_editor, tables, stdout=None) -> bool:
    """Create the triggers for the tables; on a missing privilege print a warning and carry on."""
    from django.db import OperationalError, ProgrammingError

    try:
        with schema_editor.connection.cursor() as cursor:
            for table in tables:
                for statement in drop_statements(table) + append_only_statements(table):
                    cursor.execute(statement)
    except (OperationalError, ProgrammingError) as error:
        print(  # noqa: T201
            f"Triggers not created: {error}. The model guards still apply; ask the server admin "
            "for the TRIGGER privilege or log_bin_trust_function_creators=1."
        )
        return False
    return True
