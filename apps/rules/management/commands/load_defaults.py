from pathlib import Path

import yaml
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.rules.models import Parameter, ParameterChange
from apps.rules.services import validate_value

REQUIRED = ("value", "type", "tier", "source", "help")


def walk(node, prefix=""):
    """Yield (dotted key, leaf) for every leaf: a dict with both `value` and `tier`."""
    for k, v in node.items():
        if isinstance(v, dict) and "value" in v and "tier" in v:
            yield prefix + k, v
        elif isinstance(v, dict):
            yield from walk(v, prefix + k + ".")


def _s(x):
    return None if x is None else str(x)


class Command(BaseCommand):
    help = "Load config/defaults.yaml into the rules.Parameter table."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Also reset values (only with DEBUG).")

    def handle(self, *args, **options):
        if options["reset"] and not settings.DEBUG:
            raise CommandError("--reset is only allowed when DEBUG is on.")
        path = Path(settings.BASE_DIR) / "config" / "defaults.yaml"
        tree = yaml.safe_load(path.read_text())
        leaves = list(walk(tree))
        for key, leaf in leaves:  # validate everything first
            missing = [r for r in REQUIRED if r not in leaf]
            if missing:
                raise CommandError(f"{key}: missing {', '.join(missing)}")
            try:
                validate_value(
                    key=key,
                    type=leaf["type"],
                    value=leaf["value"],
                    min_value=leaf.get("min"),
                    max_value=leaf.get("max"),
                    choices=leaf.get("choices"),
                )
            except ValidationError as e:
                raise CommandError(f"{key}: {'; '.join(e.messages)}") from None
        created = updated = unchanged = 0
        with transaction.atomic():
            for key, leaf in leaves:
                fields = {
                    "type": leaf["type"],
                    "min_value": _s(leaf.get("min")),
                    "max_value": _s(leaf.get("max")),
                    "choices": leaf.get("choices"),
                    "tier": leaf["tier"],
                    "source": leaf["source"],
                    "help": leaf["help"],
                }
                p = Parameter.objects.filter(key=key).first()
                if p is None:
                    p = Parameter.objects.create(key=key, value=leaf["value"], **fields)
                    ParameterChange.objects.create(
                        parameter=p,
                        old_value=None,
                        new_value=leaf["value"],
                        decided_by="defaults-file",
                        decided_tier="hard",
                        reason="Loaded from config/defaults.yaml",
                    )
                    created += 1
                    continue
                changed = any(getattr(p, f) != v for f, v in fields.items())
                for f, v in fields.items():
                    setattr(p, f, v)
                if options["reset"] and p.value != leaf["value"]:
                    ParameterChange.objects.create(
                        parameter=p,
                        old_value=p.value,
                        new_value=leaf["value"],
                        decided_by="defaults-file",
                        decided_tier="hard",
                        reason="Reset from config/defaults.yaml",
                    )
                    p.value = leaf["value"]
                    changed = True
                if changed:
                    p.save()
                    updated += 1
                else:
                    unchanged += 1
        self.stdout.write(f"{created} created, {updated} updated, {unchanged} unchanged.")
