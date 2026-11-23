"""Accessibility basics (P14.T11): labels, alt text, one h1, a skip link, and an installable app that updates."""

import json
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse

from apps.market.tests.conftest import World, fund  # noqa: F401
from apps.tickets.tests.conftest import CHECK, pool


class PageFacts(HTMLParser):
    """Collects what the checks need: fields, labels, images and headings."""

    NO_LABEL_NEEDED = {"hidden", "submit", "button", "image", "reset"}

    def __init__(self):
        super().__init__()
        self.fields = []  # (tag, attrs, inside_label)
        self.label_for = set()
        self.images = []
        self.h1 = 0
        self.label_depth = 0
        self.ids = set()
        self.links_without_href = 0
        self.skip_link = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        elif tag in ("input", "select", "textarea"):
            if not (tag == "input" and a.get("type", "text") in self.NO_LABEL_NEEDED):
                self.fields.append((tag, a, self.label_depth > 0))
        elif tag == "img":
            self.images.append(a)
        elif tag == "h1":
            self.h1 += 1
        elif tag == "a":
            if "href" not in a:
                self.links_without_href += 1
            if a.get("class") and "skip-link" in a["class"] and a.get("href") == "#content":
                self.skip_link = True

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1

    def unlabelled(self):
        bad = []
        for tag, a, inside in self.fields:
            if inside or a.get("aria-label") or a.get("aria-labelledby") or a.get("id") in self.label_for:
                continue
            bad.append(f"<{tag} name={a.get('name')!r} id={a.get('id')!r}>")
        return bad


def facts(html):
    parser = PageFacts()
    parser.feed(html)
    return parser


@pytest.fixture
def pages(db):
    """The main pages, with a member who is logged in."""
    from apps.tickets import services as ticket_services
    from apps.units.models import Unit

    call_command("load_defaults", stdout=StringIO())
    world = World()
    me = world.buyer("me@x.org")
    pool(12)
    ticket = ticket_services.create_ticket("delegate", me, "A ticket", brief="The brief.", check=CHECK)
    unit = Unit.objects.get(slug="bakery")
    return {
        "home": reverse("core:home"),
        "market": reverse("market:index"),
        "an offer": reverse("catalogue:offer", args=[world.bread.pk]),
        "a recipe": (reverse("catalogue:recipe", args=[world.bread.pk]), world.baker),
        "a ticket": reverse("tickets:detail", args=[ticket.number]),
        "the tickets": reverse("tickets:list"),
        "my account": reverse("members:my_account"),
        "my hours": reverse("units:my_hours"),
        "a unit": reverse("units:unit", args=[unit.slug]),
        "needs": reverse("market:needs"),
        "the rules": reverse("rules:index"),
        "imprint": reverse("core:imprint"),
    }, me


def test_main_pages_have_labels_alt_and_one_h1(pages, client):
    urls, me = pages
    problems = []
    for name, url in urls.items():
        if isinstance(url, tuple):  # a page for one particular member
            url, who = url
            client.force_login(who.user)
        else:
            client.force_login(me.user)
        response = client.get(url)
        assert response.status_code == 200, (name, response.status_code)
        page = facts(response.content.decode())
        if page.h1 != 1:
            problems.append(f"{name}: {page.h1} h1 headings")
        problems += [f"{name}: no label for {field}" for field in page.unlabelled()]
        problems += [f"{name}: image without alt: {img.get('src')}" for img in page.images if "alt" not in img]
        if not page.skip_link:
            problems.append(f"{name}: no skip link")
        if page.links_without_href:
            problems.append(f"{name}: {page.links_without_href} links without a destination")
    assert not problems, "\n".join(problems)


def test_the_skip_link_points_at_the_main_area(client):
    html = client.get("/").content.decode()
    assert 'href="#content"' in html and 'id="content"' in html
    assert html.index("skip-link") < html.index("<nav")


def test_the_page_names_its_language_and_regions(client):
    html = client.get("/").content.decode()
    assert '<html lang="en"' in html
    assert 'aria-label="Main menu"' in html and 'aria-label="About Unicorn"' in html


def test_the_regions_that_htmx_replaces_are_polite_live_regions():
    root = Path(settings.BASE_DIR)
    for path in (root / "apps").rglob("*.html"):
        text = path.read_text()
        if "hx-get" in text or "hx-post" in text:
            assert "aria-live" in text, f"{path} uses htmx but has no aria-live region"


def test_no_page_asks_htmx_to_run_code():
    root = Path(settings.BASE_DIR)
    for path in list((root / "apps").rglob("*.html")) + list((root / "templates").rglob("*.html")):
        text = path.read_text()
        assert "hx-vals='js:" not in text and 'hx-vals="js:' not in text, path
        assert "hx-on" not in text, path


def test_the_service_worker_contains_the_version(client, settings):
    settings.UNICORN_VERSION = "2026.11.3"
    body = client.get("/sw.js").content.decode()
    assert "unicorn-static-2026.11.3" in body and "__UNICORN_VERSION__" not in body
    settings.UNICORN_VERSION = "2026.12.0"
    assert "unicorn-static-2026.12.0" in client.get("/sw.js").content.decode()


def test_the_offline_page_says_unicorn_needs_a_connection(client):
    html = client.get("/offline/").content.decode()
    assert "needs a connection" in html and html.count("<h1>") == 1


def test_the_manifest_has_language_description_and_maskable_icons():
    manifest = json.loads((Path(settings.BASE_DIR) / "static" / "manifest.webmanifest").read_text())
    assert manifest["lang"] == "en" and manifest["description"]
    purposes = {icon["purpose"] for icon in manifest["icons"]}
    assert {"any", "maskable"} <= purposes
    for icon in manifest["icons"]:
        assert (Path(settings.BASE_DIR) / icon["src"].removeprefix("/")).exists(), icon["src"]


def test_focus_is_visible_and_muted_text_has_enough_contrast():
    css = (Path(settings.BASE_DIR) / "static" / "css" / "unicorn.css").read_text()
    assert ":focus-visible" in css and "outline: 3px" in css
    assert ".skip-link" in css

    def luminance(hex_colour):
        channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def ratio(a, b):
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    assert ratio("#565e64", "#f8f9fa") >= 4.5  # muted text on Bootstrap's light grey (the menu bar)
    assert ratio("#1a1a8c", "#ffffff") >= 3  # the focus ring against the page (non-text contrast)
    assert ratio("#3b3b98", "#ffffff") >= 4.5  # the brand colour on white


def test_the_checker_itself_finds_missing_labels_alt_text_and_headings():
    page = facts(
        '<h1>a</h1><h1>b</h1><input name="x"><label for="y">Y</label><input id="y">'
        '<label>Z <select name="z"></select></label><textarea aria-label="t"></textarea>'
        '<img src="a.png"><input type="hidden">'
    )
    assert page.h1 == 2
    assert page.unlabelled() == ["<input name='x' id=None>"]
    assert [i for i in page.images if "alt" not in i]
