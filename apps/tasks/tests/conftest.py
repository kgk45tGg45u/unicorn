from io import StringIO

import pytest
from django.core.management import call_command

from apps.tickets.tests.conftest import CHECK, answer, make_member, make_unit, open_seats, pool  # noqa: F401


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())
