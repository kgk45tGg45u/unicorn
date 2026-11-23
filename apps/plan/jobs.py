"""The plan's daily job: the calendar moves the period along (docs/05 section 8). Safe to run twice."""

from apps.core.jobs import job

from . import apply, calendar, group, services, variants, vote
from .models import PlanningGroup


@job("plan.daily")
def daily(payload):
    run(services.today())


def run(on) -> dict:
    """Every step checks its own state, so running this twice in a day does nothing more."""
    done = {}
    if on >= calendar.on("proposals_open", on.year):  # the season of the plan that starts next 1 January
        period = services.next_period(on)

        def day(key):
            return calendar.on(key, on.year)

        if (
            period.status == "proposals"
            and on >= day("group_drawn")
            and not PlanningGroup.objects.filter(period=period).exists()
        ):
            group.draw_group(period, on=on)
            period.status = "drafting"
            period.save(update_fields=["status"])
            done["group"] = True
        if period.status == "drafting" and on > day("drafting_close"):
            try:
                variants.finish_drafting(period)
                done["drafting_closed"] = True
            except services.PlanError:
                done["drafting_failed"] = True
        if period.status == "comments" and on >= day("vote_open"):
            vote.start_vote(period, on)
            done["vote"] = True
    group.expire_unanswered(on)
    done["repeated"] = apply.repeat_vote(on)
    done["started"] = apply.start_due_periods(on)
    done["closures"] = apply.run_closures(on)
    done["closed_units"] = apply.finish_closing_units()
    return done
