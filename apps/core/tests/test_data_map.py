from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import models

PERSONAL_NAMES = {"email", "display_name", "postcode", "receives_benefits"}


def personal_fields():
    """Every field that holds personal data: encrypted columns, binary columns and the named plain fields."""
    found = set()
    for model in apps.get_models():
        if not model.__module__.startswith("apps."):
            continue
        for field in model._meta.get_fields():
            if not hasattr(field, "column") or field.many_to_many:
                continue
            if field.name.endswith("_enc") or isinstance(field, models.BinaryField) or field.name in PERSONAL_NAMES:
                found.add(f"{model._meta.label}.{field.name}")
    return found


def test_hf14_data_map_covers_personal_fields():
    text = (Path(settings.BASE_DIR) / "docs" / "privacy" / "data_map.md").read_text()
    missing = sorted(name for name in personal_fields() if name not in text)
    assert missing == [], f"Add these fields to docs/privacy/data_map.md: {missing}"


def test_the_data_map_gives_a_legal_basis_and_a_time_for_every_row():
    rows = [
        line
        for line in (Path(settings.BASE_DIR) / "docs" / "privacy" / "data_map.md").read_text().splitlines()
        if line.startswith("| ") and not line.startswith("| What") and not line.startswith("|---")
    ]
    assert len(rows) > 25
    assert all(len(line.strip("|").split("|")) == 6 for line in rows)
