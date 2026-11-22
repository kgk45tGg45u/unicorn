from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import (
    Comment,
    Confirmation,
    Conflict,
    Flag,
    HelpfulMark,
    Hidden,
    MediationMessage,
    Notification,
    Seat,
    Ticket,
)


@admin.register(Ticket)
class TicketAdmin(ReadOnlyAdmin):
    list_display = ("number", "type", "title", "status", "created_at")


@admin.register(Comment)
class CommentAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "author", "created_at")


@admin.register(HelpfulMark)
class HelpfulMarkAdmin(ReadOnlyAdmin):
    list_display = ("comment", "member", "created_at")


@admin.register(Notification)
class NotificationAdmin(ReadOnlyAdmin):
    list_display = ("member", "text", "created_at", "read_at")


@admin.register(Flag)
class FlagAdmin(ReadOnlyAdmin):
    list_display = ("target_type", "target_id", "reason", "ticket", "created_at")


@admin.register(Hidden)
class HiddenAdmin(ReadOnlyAdmin):
    list_display = ("target_type", "target_id", "since", "until")


@admin.register(Confirmation)
class ConfirmationAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "round", "status", "eligible_count", "created_at")


@admin.register(Seat)
class SeatAdmin(ReadOnlyAdmin):
    list_display = ("confirmation", "member", "vote", "replaced", "deadline")


@admin.register(Conflict)
class ConflictAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "member", "created_at")


@admin.register(MediationMessage)
class MediationMessageAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "author", "created_at")
