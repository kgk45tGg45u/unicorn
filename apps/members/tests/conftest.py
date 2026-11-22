from io import StringIO

import pytest
from django.core.management import call_command


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    """Some member flows now open tickets, which read the democratic defaults."""
    call_command("load_defaults", stdout=StringIO())
