from django.core.management.base import BaseCommand

from apps.plan import services


class Command(BaseCommand):
    help = "Create the first plan period and the yes/no vote on the default plan (the founders' launch)."

    def handle(self, *args, **options):
        period = services.start_first_plan()
        self.stdout.write(f"First plan {period.starts_on} to {period.ends_on}: vote {period.referendum.pk} scheduled.")
