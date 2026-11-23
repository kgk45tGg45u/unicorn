from django.db import models


class FxRate(models.Model):
    """The ECB reference rate of a day: units of the currency per 1 EUR. Never an exchange rate for UNIQ (HF-4)."""

    date = models.DateField()
    currency = models.CharField(max_length=3)
    per_eur = models.DecimalField(max_digits=18, decimal_places=6)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["date", "currency"], name="unique_fx_per_day")]
        ordering = ["-date", "currency"]

    def __str__(self):
        return f"{self.date} 1 EUR = {self.per_eur} {self.currency}"
