from django import forms
from django.utils.translation import gettext_lazy as _


class AboutYouForm(forms.Form):
    display_name = forms.CharField(label=_("Display name (other members see this)"), max_length=60)
    country = forms.CharField(
        label=_("Country (two letters, for example DE)"), min_length=2, max_length=2, initial="DE"
    )
    currency = forms.CharField(
        label=_("Currency (three letters, for example EUR)"), min_length=3, max_length=3, initial="EUR"
    )
    postcode = forms.CharField(label=_("Postcode (the area only, no street)"), max_length=12, required=False)
    legal_name = forms.CharField(label=_("Your legal name (kept private and encrypted)"), max_length=120)
    birth_date = forms.DateField(
        label=_("Date of birth (YYYY-MM-DD, kept private and encrypted)"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    phone = forms.CharField(label=_("Phone (optional, kept private and encrypted)"), max_length=40, required=False)
    receives_benefits = forms.BooleanField(label=_("I receive means-tested benefits"), required=False)

    def clean_country(self):
        return self.cleaned_data["country"].upper()

    def clean_currency(self):
        return self.cleaned_data["currency"].upper()
