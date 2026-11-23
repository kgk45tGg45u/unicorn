from django.core.management.base import BaseCommand
from django.db import transaction

from apps.members import services
from apps.members.models import Member
from apps.privacy.models import DeletionRecord


class Command(BaseCommand):
    help = (
        "Repeat the deletion of every deleted member. Run it after restoring a backup: the backup still holds "
        "their plain email address and display name."
    )

    def handle(self, *args, **options):
        done = 0
        for record in DeletionRecord.objects.all():
            member = Member.objects.filter(number=record.member_number).first()
            if member is None:
                continue
            old_email = "" if member.user.email.endswith("@invalid") else member.user.email
            with transaction.atomic():
                services.erase_traces(member, old_email)
            done += 1
        self.stdout.write(f"{done} deleted member(s) cleaned again.")
