"""The plan calendar (`plan.calendar.*`): each day is a month-day text such as "09-01"."""

from datetime import date

from apps.rules.services import get_param


def on(key: str, year: int) -> date:
    month, day = (int(x) for x in get_param(f"plan.calendar.{key}").split("-"))
    return date(year, month, day)


def plan_year(today: date) -> int:
    """The year the next plan starts in: the proposals of July to December are for the following year."""
    return today.year + 1 if today >= on("proposals_open", today.year) else today.year
