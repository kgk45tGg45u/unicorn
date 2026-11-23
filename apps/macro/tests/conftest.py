from io import StringIO

import pytest
from django.core.management import call_command

from apps.units.tests.conftest import make_member, make_unit  # noqa: F401


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())
    call_command("loaddata", "contracts", verbosity=0)
