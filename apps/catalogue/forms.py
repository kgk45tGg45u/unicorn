from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Offer


class ProductOfferForm(forms.ModelForm):
    class Meta:
        model = Offer
        fields = ["batch_size", "min_batch", "cycle_days", "setup_minutes", "direct_minutes_per_batch"]
        labels = {
            "batch_size": _("How many does one batch make?"),
            "min_batch": _("Smallest batch worth starting"),
            "cycle_days": _("Days from start until the batch is ready"),
            "setup_minutes": _("Setup minutes per batch (heating the oven, setting up a machine)"),
            "direct_minutes_per_batch": _("Working minutes per batch, all workers together"),
        }


class ServiceOfferForm(forms.ModelForm):
    class Meta:
        model = Offer
        fields = ["duration_minutes", "capacity", "travel_minutes", "place", "max_per_week"]
        labels = {
            "duration_minutes": _("Minutes per session"),
            "capacity": _("Customers served at once"),
            "travel_minutes": _("Travel minutes (when it happens at the customer's place)"),
            "place": _("Where does it happen?"),
            "max_per_week": _("Most sessions a week (optional)"),
        }
