from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import ContractTemplate, Member, Signature


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
