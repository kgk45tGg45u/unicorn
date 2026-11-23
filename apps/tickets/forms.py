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
        if info.key == "task_list":
            self.fields["tasks"] = forms.CharField(
                label=_("The tasks, one per line: title | minutes | what to do (optional)"),
                widget=forms.Textarea(attrs={"rows": 6}),
            )
        if info.key == "delegate":
            self.fields["spend_limit_eur"] = forms.DecimalField(
                label=_("Most the delegate may spend, in euros (through payment requests)"),
                min_value=0,
                required=False,
            )
            self.fields["may_sign"] = forms.BooleanField(label=_("The delegate may sign for Unicorn"), required=False)
            self.fields["may_represent"] = forms.BooleanField(
                label=_("The delegate may speak for Unicorn"), required=False
            )

    def clean_tasks(self):
        rows = []
        for line in self.cleaned_data["tasks"].splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2 or not parts[0] or not parts[1].isdigit() or int(parts[1]) < 1:
                raise forms.ValidationError(_("Each line needs a title and the minutes, like: Clean the room | 60"))
            rows.append(
                {"title": parts[0], "minutes": int(parts[1]), "description": parts[2] if len(parts) > 2 else ""}
            )
        if not rows:
            raise forms.ValidationError(_("Please add at least one task."))
        return rows

    def extra_payload(self):
        d = self.cleaned_data
        if self.info.key == "task_list":
            return {"tasks": d["tasks"]}
        if self.info.key == "delegate":
            return {
                "needs_delegate": True,
                "powers": {
                    "spend_limit_eur": float(d.get("spend_limit_eur") or 0),
                    "may_sign": bool(d.get("may_sign")),
                    "may_represent": bool(d.get("may_represent")),
                },
            }
        return {}

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


class HardFrameForm(forms.Form):
    rule = forms.CharField(label=_("The rule (HF-2) or the bound (a default's key) that should change"), max_length=120)
    new_text = forms.CharField(label=_("The new text or value"), widget=forms.Textarea(attrs={"rows": 3}))
    why = forms.CharField(label=_("Why it is needed"), widget=forms.Textarea(attrs={"rows": 3}))
    code_change = forms.CharField(label=_("What changes in the code"), widget=forms.Textarea(attrs={"rows": 3}))
    authors = forms.CharField(
        label=_("The authors, one per line: name | one sentence about their expertise"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    forecast = forms.FileField(label=_("The forecast (a file, required)"))
    brief = forms.CharField(
        label=_("Anything else for the readers (optional)"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    check_question = forms.CharField(label=_("A question about this proposal"), max_length=300)
    answer_0 = forms.CharField(label=_("Answer 1"), max_length=120)
    answer_1 = forms.CharField(label=_("Answer 2"), max_length=120)
    answer_2 = forms.CharField(label=_("Answer 3"), max_length=120)
    correct = forms.ChoiceField(label=_("Which answer is right?"), choices=[("0", "1"), ("1", "2"), ("2", "3")])
    check_hint = forms.CharField(
        label=_("Where is the answer? (shown after a wrong answer)"), max_length=200, required=False
    )

    def clean_authors(self):
        rows = []
        for line in self.cleaned_data["authors"].splitlines():
            if line.strip():
                name, _sep, expertise = line.partition("|")
                rows.append({"name": name.strip(), "expertise": expertise.strip()})
        return rows

    def check(self):
        d = self.cleaned_data
        return {
            "question": d["check_question"],
            "choices": [d["answer_0"], d["answer_1"], d["answer_2"]],
            "correct": int(d["correct"]),
            "hint": d.get("check_hint", ""),
        }
