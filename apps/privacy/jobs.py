from apps.core.jobs import job

from . import export
from .models import DataExport


@job("privacy.export")
def make_export(payload):
    """Build one member's data export. Safe to run twice."""
    row = DataExport.objects.filter(pk=payload["export"]).select_related("member").first()
    if row is not None:
        export.create_export(row)


@job("privacy.cleanup")
def cleanup(payload):
    """Delete exports after 7 days. Safe to run twice."""
    export.delete_files()
