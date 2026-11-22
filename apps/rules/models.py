from django.db import models

TIER_CHOICES = [(t, t) for t in ("unit", "confirm", "plan", "referendum", "hard")]
TYPE_CHOICES = [(t, t) for t in ("decimal", "int", "bool", "choice", "text", "list")]


class Parameter(models.Model):
    """One democratic default. The database holds the live value (docs/01 section 2)."""

    key = models.CharField(max_length=120, unique=True)
    value = models.JSONField()
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    min_value = models.CharField(max_length=40, null=True, blank=True)  # noqa: DJ001  strings keep decimals exact (plan P00.T07)
    max_value = models.CharField(max_length=40, null=True, blank=True)  # noqa: DJ001
    choices = models.JSONField(null=True, blank=True)
    tier = models.CharField(max_length=10, choices=TIER_CHOICES)
    source = models.CharField(max_length=200)
    help = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value}"


class ParameterChange(models.Model):
    """One change of a parameter. Append-only."""

    parameter = models.ForeignKey(Parameter, on_delete=models.PROTECT, related_name="changes")
    old_value = models.JSONField(null=True)
    new_value = models.JSONField()
    decided_by = models.CharField(max_length=32)  # a ticket number such as T-000123, or "defaults-file"
    decided_tier = models.CharField(max_length=10, choices=TIER_CHOICES)
    reason = models.TextField()
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-decided_at", "-id"]

    def __str__(self):
        return f"{self.parameter.key}: {self.old_value} -> {self.new_value}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Parameter changes cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Parameter changes cannot be deleted.")
