from io import StringIO

import pytest
from allauth.account.models import EmailAddress
from django.apps import apps
from django.core.management import call_command
from django.db import models

from apps.members import services as member_services
from apps.members.models import Member, MemberHash, PrivateFile, Skill, Waitlist
from apps.privacy.models import DataExport, DeletionRecord
from apps.tickets import services as ticket_services
from apps.tickets.models import Notification
from apps.units import services as unit_services
from apps.units.tests.conftest import make_unit

from .conftest import make_member

pytestmark = pytest.mark.django_db

EMAIL = "zyxwvut.quux@example.org"
NAME = "Zyxwvut Quux"


def a_busy_member():
    """A member who left traces in many places."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    member = make_member(EMAIL, NAME)
    member_services.set_private(member, legal_name="Zelda Zyxwvut", city="Bremen", iban="DE89370400440532013000")
    member_services.store_private_file(member, SimpleUploadedFile("doc.pdf", b"%PDF-1.4 x", "application/pdf"), "other")
    EmailAddress.objects.create(user=member.user, email=EMAIL, verified=True, primary=True)
    Waitlist.objects.create(email=EMAIL)
    Skill.objects.create(member=member, trade_name="Baking", level="able")
    MemberHash.objects.create(member=member, kind="email", value="ab" * 32)
    Notification.objects.create(member=member, text="Something happened")
    unit = make_unit("bakery")
    unit_services.add_first_worker(unit, make_member("other@x.org", "Other"))
    ticket = ticket_services.create_ticket("question", make_member("o2@x.org", "O2"), "A question")
    ticket_services.add_comment(ticket, member, "My considered answer")
    DataExport.objects.create(member=member)
    Member.objects.filter(pk=member.pk).update(postcode="28195", public_profile=True)
    member.refresh_from_db()
    return member


def text_fields():
    """Every text or char column of every model, except the ones that cannot hold a person's words."""
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if isinstance(field, (models.CharField, models.TextField, models.JSONField)) and not field.primary_key:
                yield model, field


def find_plaintext(*needles):
    found = []
    for model, field in text_fields():
        if model._meta.label in ("sessions.Session",):
            continue
        for needle in needles:
            lookup = f"{field.name}__icontains"
            try:
                if model.objects.filter(**{lookup: needle}).exists():
                    found.append(f"{model._meta.label}.{field.name} has {needle}")
            except Exception:  # noqa: BLE001  a lookup that a column type cannot do holds no text to find
                continue
    return found


def test_hf14_deleted_member_leaves_no_plaintext():
    member = a_busy_member()
    assert find_plaintext(EMAIL, NAME)  # the setup does leave traces
    member_services.delete_account(member)
    assert find_plaintext(EMAIL, NAME, "Zelda") == []
    member.refresh_from_db()
    assert member.display_name == f"Former member {member.number}" and member.postcode == ""
    assert member.public_profile is False and member.deleted
    assert DeletionRecord.objects.get().member_number == member.number
    assert not EmailAddress.objects.filter(user=member.user).exists()
    assert not Notification.objects.filter(member=member).exists() and not DataExport.objects.exists()
    assert not Skill.objects.filter(member=member).exists() and not MemberHash.objects.exists()


def test_comments_keep_their_text_and_show_a_former_member():
    member = a_busy_member()
    member_services.delete_account(member)
    from apps.tickets.models import Comment

    comment = Comment.objects.get()
    assert comment.body_md == "My considered answer" and comment.author.display_name.startswith("Former member")


def test_the_private_files_are_removed_from_the_disk(settings):
    from pathlib import Path

    member = a_busy_member()
    pf = PrivateFile.objects.get(owner=member)
    on_disk = Path(settings.PRIVATE_MEDIA_ROOT) / pf.path
    assert on_disk.exists()
    member_services.delete_account(member)
    assert not on_disk.exists()
    assert PrivateFile.objects.get(pk=pf.pk).path == ""
    assert not list(Path(settings.PRIVATE_MEDIA_ROOT).rglob("*.bin"))


def test_reapply_deletions_cleans_a_database_restored_from_before_the_deletion():
    member = a_busy_member()
    member_services.delete_account(member)
    # a restore from an old backup brings the plain data back
    Member.objects.filter(pk=member.pk).update(display_name=NAME, postcode="28195", public_profile=True)
    user = member.user
    user.email = EMAIL
    user.save()
    EmailAddress.objects.create(user=user, email=EMAIL, verified=True, primary=True)
    assert find_plaintext(EMAIL, NAME)
    call_command("reapply_deletions", stdout=StringIO())
    assert find_plaintext(EMAIL, NAME) == []
    member.refresh_from_db()
    assert member.display_name.startswith("Former member") and member.deleted
    call_command("reapply_deletions", stdout=StringIO())  # safe to run twice
