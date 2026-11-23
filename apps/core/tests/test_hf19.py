from pathlib import Path

import pytest
from django.conf import settings

pytestmark = pytest.mark.django_db


def test_hf19_licence_and_source_link(client, settings):
    root = Path(settings.BASE_DIR)
    licence = (root / "LICENSE").read_text()
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in licence and "Version 3" in licence
    assert 'license = "AGPL-3.0-or-later"' in (root / "pyproject.toml").read_text()
    settings.SOURCE_URL = "https://example.org/unicorn-source"
    settings.UNICORN_VERSION = "2026.11.23"
    html = client.get("/").content.decode()
    assert 'href="https://example.org/unicorn-source"' in html and "Source code" in html
    assert "Version 2026.11.23" in html
    banned = ("paywall", "subscription", "premium")
    offenders = [
        str(path.relative_to(root))
        for path in (root / "apps").rglob("*.py")
        if "tests" not in path.parts and any(word in path.read_text().lower() for word in banned)
    ]
    assert offenders == []  # nothing in Unicorn can be paid for to get more (HF-19)


def test_the_licence_text_is_the_unchanged_agpl_3():
    import hashlib

    text = (Path(settings.BASE_DIR) / "LICENSE").read_bytes()
    assert text.count(b"GNU AFFERO GENERAL PUBLIC LICENSE") >= 1
    assert len(text) > 30000 and hashlib.sha256(text).hexdigest()  # the full text, not a summary
