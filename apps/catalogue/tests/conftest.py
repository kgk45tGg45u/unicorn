from io import StringIO

import pytest
from django.core.management import call_command


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())
