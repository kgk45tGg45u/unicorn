from django.apps import AppConfig


class VotesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.votes"
    label = "votes"

    def ready(self):
        from apps.core.management.commands import daily
        from apps.tickets import actions

        from . import elections, jobs  # noqa: F401

        actions.register("start_elections", elections.start_first_elections)

        for entry in (
            ("votes.close_petitions", {}),
            ("votes.open_referendums", {}),
            ("votes.close_referendums", {}),
            ("votes.close_elections", {}),
            ("votes.yearly_elections", {}),
        ):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
