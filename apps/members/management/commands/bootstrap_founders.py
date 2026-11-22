from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.members.models import ContractTemplate, Member, Signature
from apps.rules.services import get_param


class Command(BaseCommand):
    help = "For the founding meeting: mark the listed members as verified founders."

    def add_arguments(self, parser):
        parser.add_argument("--emails", nargs="+", required=True)

    def handle(self, *args, **options):
        from apps.members.services import VERIFIED_HOOKS

        target = get_param("membership.founders_target")
        with transaction.atomic():
            if Member.objects.filter(status=Member.MEMBER).count() > target:
                raise CommandError(f"More than {target} verified members exist already; founders can no longer be set.")
            template = ContractTemplate.objects.filter(kind="membership", is_current=True).first()
            members = []
            for email in options["emails"]:
                member = Member.objects.filter(user__email__iexact=email).first()
                if member is None:
                    raise CommandError(f"No member with the email {email}.")
                if template is None or not Signature.objects.filter(member=member, template=template).exists():
                    raise CommandError(f"{email} has not signed the contract.")
                members.append(member)
            for member in members:
                member.is_founder = True
                if member.status != Member.MEMBER:
                    member.status = Member.MEMBER
                    member.verified_at = timezone.now()
                member.save()
                for hook in VERIFIED_HOOKS:
                    hook(member)
            audit.record("system", "founders_verified", numbers=[m.number for m in members])
        self.stdout.write(f"{len(members)} founder(s) verified.")
