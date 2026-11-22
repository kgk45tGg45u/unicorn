from django.db import models


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
