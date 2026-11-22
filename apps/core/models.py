from django.db import models
from django.utils import timezone


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditEvent(models.Model):
    """One recorded action. Append-only; holds member numbers and ids, never personal data."""

    created_at = models.DateTimeField(auto_now_add=True)
    actor_ref = models.CharField(max_length=32)  # a member number or "system"
    verb = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict)
    request_id = models.CharField(max_length=36, blank=True)

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_ref} {self.verb}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Audit events cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit events cannot be deleted.")


class Job(models.Model):
    """A background job, run by `manage.py run_jobs` (cron calls it every minute)."""

    QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
    STATUS_CHOICES = [(QUEUED, "queued"), (RUNNING, "running"), (DONE, "done"), (FAILED, "failed")]

    kind = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=QUEUED)
    run_after = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    last_error = models.TextField(blank=True)
    dedupe_key = models.CharField(max_length=128, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "run_after"])]

    def __str__(self):
        return f"{self.kind} ({self.status})"
