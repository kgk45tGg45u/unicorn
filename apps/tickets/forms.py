from django import forms
from django.utils.translation import gettext_lazy as _


class TicketForm(forms.Form):
    title = forms.CharField(label=_("Title"), max_length=160)
    body = forms.CharField(
        label=_("What do you want to say?"), widget=forms.Textarea(attrs={"rows": 6}), required=False
    )
    unit = forms.ModelChoiceField(label=_("Which unit?"), queryset=None, required=False)
    brief = forms.CharField(
        label=_("Brief for the people who decide (at most 500 words)"),
        widget=forms.Textarea(attrs={"rows": 6}),
        required=False,
    )
    check_question = forms.CharField(label=_("A question about the brief"), max_length=300, required=False)
    answer_0 = forms.CharField(label=_("Answer 1"), max_length=120, required=False)
    answer_1 = forms.CharField(label=_("Answer 2"), max_length=120, required=False)
    answer_2 = forms.CharField(label=_("Answer 3"), max_length=120, required=False)
    correct = forms.ChoiceField(
        label=_("Which answer is right?"), choices=[("0", "1"), ("1", "2"), ("2", "3")], required=False
    )
    check_hint = forms.CharField(
        label=_("Where in the brief is the answer? (shown after a wrong answer)"), max_length=200, required=False
    )

    def __init__(self, *args, info, **kwargs):
        from apps.units.models import Unit

        super().__init__(*args, **kwargs)
        self.info = info
        self.fields["unit"].queryset = Unit.objects.exclude(status__in=["closed", "merged"]).exclude(
            kind="coordination"
        )
        if not info.unit_scope:
            del self.fields["unit"]
        else:
            self.fields["unit"].required = True
        if not info.needs_brief:
            for name in ("brief", "check_question", "answer_0", "answer_1", "answer_2", "correct", "check_hint"):
                del self.fields[name]

    def check(self):
        d = self.cleaned_data
        if not self.info.needs_brief:
            return None
        return {
            "question": d.get("check_question", ""),
            "choices": [d.get("answer_0", ""), d.get("answer_1", ""), d.get("answer_2", "")],
            "correct": int(d["correct"]) if d.get("correct") else None,
            "hint": d.get("check_hint", ""),
        }
