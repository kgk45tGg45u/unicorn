from django.db import models


class DataExport(models.Model):
    """A member's download of their own data: an encrypted ZIP in private storage, kept for 7 days."""

    QUEUED, READY, EXPIRED, FAILED = "queued", "ready", "expired", "failed"
    STATUSES = [(QUEUED, "queued"), (READY, "ready"), (EXPIRED, "expired"), (FAILED, "failed")]

    member = models.ForeignKey("members.Member", on_delete=models.CASCADE, related_name="data_exports")
    status = models.CharField(max_length=8, choices=STATUSES, default=QUEUED)
    path = models.CharField(max_length=200, blank=True)  # relative to PRIVATE_MEDIA_ROOT
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"export {self.pk} of {self.member.number} ({self.status})"


class DeletionRecord(models.Model):
    """A member's account was deleted completely. It holds no personal data: only the number and the day (P14.T04)."""

    member_number = models.CharField(max_length=12, unique=True)
    deleted_at = models.DateTimeField()

    class Meta:
        ordering = ["-deleted_at"]

    def __str__(self):
        return f"{self.member_number} deleted {self.deleted_at:%Y-%m-%d}"
