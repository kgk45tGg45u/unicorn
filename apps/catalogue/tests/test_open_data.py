import re

import pytest
from django.urls import reverse

from apps.catalogue import services

from .test_values import world

pytestmark = pytest.mark.django_db


def test_the_summary_page(client):
    world()
    services.recompute_values()
    page = client.get(reverse("catalogue:io_table")).content.decode()
    assert "Active offers" in page and "€0.13" in page
    assert "not yet" not in page


def test_the_csvs_have_the_right_headers_and_no_member_numbers(client):
    m, mill, bake = world()
    services.add_input(m, bake, "Eggs", "pc", 2, "own_free", provided_by=m)
    services.add_tool(m, bake, "My oven", "own_free", 1, 1000, provided_by=m)
    services.recompute_values()
    headers = {
        "io_offers_csv": "offer_id,unit,item,kind,uom,basis,direct_hours,indirect_hours,total_hours,euro_content",
        "io_inputs_csv": "offer_id,item,quantity_per_batch,source,preferred_supplier_offer_id",
        "io_tools_csv": "offer_id,tool,source,uses_per_batch,lifetime_uses",
    }
    for name, header in headers.items():
        response = client.get(reverse(f"catalogue:{name}"))
        text = response.content.decode()
        assert response["Content-Type"].startswith("text/csv")
        assert text.splitlines()[0] == header
        assert len(text.splitlines()) > 1
        assert not re.search(r"M-[0-9A-Z]{4}-[0-9A-Z]{4}", text)
        assert m.display_name not in text and m.user.email not in text
