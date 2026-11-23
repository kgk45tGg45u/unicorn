from django.core.management.base import BaseCommand
from django.db import transaction

from apps.members import crypto, services
from apps.members.models import Member, MemberHash


class Command(BaseCommand):
    help = (
        "Recompute every duplicate-detection hash with the new UNICORN_HMAC_KEY, from the member's decrypted private "
        "data and email. Members whose key was destroyed have no hashes left. Safe to run twice."
    )

    def handle(self, *args, **options):
        done = 0
        ids = list(MemberHash.objects.values_list("member_id", flat=True).distinct())
        for member in Member.objects.filter(pk__in=ids).select_related("user"):
            try:
                wanted = services.wanted_hashes(member)
            except crypto.KeyDestroyed:
                continue
            with transaction.atomic():
                MemberHash.objects.filter(member=member).delete()
                for kind, raw in wanted.items():
                    MemberHash.objects.create(member=member, kind=kind, value=services.hash_of(kind, raw))
            done += 1
        self.stdout.write(f"members whose hashes were recomputed: {done}")
