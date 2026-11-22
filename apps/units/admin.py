from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import (
    CouncilDecision,
    CouncilRules,
    CouncilVote,
    HoursEntry,
    JoinRequest,
    Responsibility,
    TimerSession,
    Unit,
    UnitMembership,
)


@admin.register(Unit)
class UnitAdmin(ReadOnlyAdmin):
    list_display = ("name", "kind", "status")


@admin.register(UnitMembership)
class UnitMembershipAdmin(ReadOnlyAdmin):
    list_display = ("unit", "member", "is_council", "joined_at", "left_at")


@admin.register(JoinRequest)
class JoinRequestAdmin(ReadOnlyAdmin):
    list_display = ("unit", "member", "status")


@admin.register(CouncilDecision)
class CouncilDecisionAdmin(ReadOnlyAdmin):
    list_display = ("unit", "title", "kind", "status")


@admin.register(CouncilVote)
class CouncilVoteAdmin(ReadOnlyAdmin):
    list_display = ("decision", "member", "vote")


@admin.register(CouncilRules)
class CouncilRulesAdmin(ReadOnlyAdmin):
    list_display = ("unit", "version", "decision_rule")


@admin.register(Responsibility)
class ResponsibilityAdmin(ReadOnlyAdmin):
    list_display = ("unit", "member", "starts_at", "ends_at", "how")


@admin.register(HoursEntry)
class HoursEntryAdmin(ReadOnlyAdmin):
    list_display = ("member", "unit", "date", "minutes", "status")


@admin.register(TimerSession)
class TimerSessionAdmin(ReadOnlyAdmin):
    list_display = ("member", "unit", "started_at")
