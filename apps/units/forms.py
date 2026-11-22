from django import forms
from django.utils.translation import gettext_lazy as _

from apps.members.models import Licence

from .models import Unit


class OpenUnitForm(forms.Form):
    name = forms.CharField(max_length=80, label=_("Name of the unit"))
    kind = forms.ChoiceField(
        choices=[c for c in Unit.KINDS if c[0] != "coordination"],
        label=_("What kind of unit is it?"),
        help_text=_(
            "Production makes things. A service does work for people. Social units look after people or places."
        ),
    )
    mode = forms.ChoiceField(choices=Unit.MODES, label=_("How does it work?"), initial="continuous")
    description = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), label=_("What will you do?"), required=False
    )
    town = forms.CharField(max_length=80, label=_("Town"), required=False)
    postcode = forms.CharField(max_length=12, label=_("Postcode"), required=False)
    country = forms.CharField(max_length=2, label=_("Country (two letters)"), required=False)
    licence_kind_required = forms.ChoiceField(
        choices=[("", _("No"))] + list(Licence.KINDS),
        required=False,
        label=_("Does this trade need a licence?"),
        help_text=_("Some trades need a licence by law. You must have it, and it must be verified."),
    )
    insurance_confirmed = forms.BooleanField(
        required=False,
        label=_("The unit is insured"),
        help_text=_("Services and social units need insurance."),
    )
