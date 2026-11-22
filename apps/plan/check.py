from dataclasses import dataclass

from django.utils.translation import gettext as _


@dataclass
class CheckPoint:
    color: str  # "green" | "amber" | "red"
    text: str


@dataclass
class CheckResult:
    points: list[CheckPoint]

    @property
    def color(self):
        return (
            "red"
            if any(p.color == "red" for p in self.points)
            else "amber"
            if any(p.color == "amber" for p in self.points)
            else "green"
        )


def check(request: dict) -> CheckResult:
    # Phase 11 replaces this with the full plan check (docs/06 section 2).
    return CheckResult([CheckPoint("green", _("There is no yearly plan yet, so nothing in it is against this."))])
