import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PAGES = [("core:imprint", "Imprint"), ("core:privacy", "Privacy notice"), ("core:terms", "Terms of use")]


@pytest.mark.parametrize(("name", "title"), PAGES)
def test_each_legal_page_loads_without_login_and_starts_with_the_draft_note(client, name, title):
    response = client.get(reverse(name))
    html = response.content.decode()
    assert response.status_code == 200 and f"<h1>{title}</h1>" in html
    assert "DRAFT — to be written with lawyers" in html
    assert "&lt;to fill in&gt;" in html  # shown as text, never as markup


def test_the_contract_page_is_public_too(client):
    from django.core.management import call_command

    call_command("loaddata", "contracts", verbosity=0)
    assert client.get(reverse("members:contract")).status_code == 200


def test_the_footer_links_to_each_page(client):
    html = client.get("/").content.decode()
    for name in ("core:imprint", "core:privacy", "core:terms", "members:contract", "core:third_party"):
        assert f'href="{reverse(name)}"' in html, name


def test_the_third_party_page_names_bootstrap_htmx_and_the_postcode_data(client):
    html = client.get(reverse("core:third_party")).content.decode()
    assert "Bootstrap" in html and "htmx" in html and "GeoNames" in html and "MIT" in html


def test_the_privacy_notice_names_the_rights_and_the_retention(client):
    html = client.get(reverse("core:privacy")).content.decode()
    for words in ("Download all my data", "data-protection authority", "12 months", "Secret ballots"):
        assert words in html


def test_the_markdown_converter_escapes_html():
    from apps.core.markdown import render

    out = render("# Title\n\n<script>alert(1)</script> and **bold**\n\n- one\n- two\n")
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "<strong>bold</strong>" in out and out.count("<li>") == 2


def test_an_unknown_legal_page_is_a_404(client):
    from apps.core.views import LEGAL_PAGES

    assert "nonsense" not in LEGAL_PAGES
    assert client.get("/legal-nonsense/").status_code == 404
