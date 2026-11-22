from io import StringIO

import pytest
from django.core.management import call_command

from apps.rules.hard_frame import RULES


def test_hf_registry_has_20_rules():
    assert [r.id for r in RULES] == [f"HF-{i}" for i in range(1, 21)]
    assert all(r.title and r.text for r in RULES)


@pytest.mark.django_db
def test_rules_page_lists_parameters(client):
    call_command("load_defaults", stdout=StringIO())
    html = client.get("/rules/").content.decode()
    assert "governance.confirmers.size" in html
    assert "HF-20" in html
