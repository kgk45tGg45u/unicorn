from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import (
    Availability,
    ContractTemplate,
    InPersonCheck,
    Licence,
    Member,
    MemberHash,
    PrivateFile,
    Signature,
    SiteState,
    Skill,
    Vouch,
    Waitlist,
)


@admin.register(Member)
class MemberAdmin(ReadOnlyAdmin):
    list_display = ("number", "display_name", "status")
    search_fields = ("number",)


@admin.register(ContractTemplate)
class ContractTemplateAdmin(ReadOnlyAdmin):
    list_display = ("title", "version", "is_current")


@admin.register(Signature)
class SignatureAdmin(ReadOnlyAdmin):
    list_display = ("member", "template", "signed_at", "method")


@admin.register(PrivateFile)
class PrivateFileAdmin(ReadOnlyAdmin):
    list_display = ("owner", "kind", "size", "created_at")
    exclude = ("name_enc",)


@admin.register(Vouch)
class VouchAdmin(ReadOnlyAdmin):
    list_display = ("voucher", "vouchee", "created_at")


@admin.register(InPersonCheck)
class InPersonCheckAdmin(ReadOnlyAdmin):
    list_display = ("helper", "member", "seen_on", "town")


@admin.register(MemberHash)
class MemberHashAdmin(ReadOnlyAdmin):
    list_display = ("member", "kind")


@admin.register(SiteState)
class SiteStateAdmin(ReadOnlyAdmin):
    list_display = ("launched_at",)


@admin.register(Waitlist)
class WaitlistAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "invited_at")
    exclude = ("email",)


@admin.register(Skill)
class SkillAdmin(ReadOnlyAdmin):
    list_display = ("member", "trade_name", "level")


@admin.register(Licence)
class LicenceAdmin(ReadOnlyAdmin):
    list_display = ("member", "kind", "status", "expires_on")


@admin.register(Availability)
class AvailabilityAdmin(ReadOnlyAdmin):
    list_display = ("member", "hours_per_week")
