from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Comment, HelpfulMark, Notification, Ticket


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
