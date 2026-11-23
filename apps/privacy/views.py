from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import sensitive_action
from apps.core.jobs import enqueue
from apps.members.assist import assist_never

from . import export
from .models import DataExport


@assist_never
@sensitive_action
@require_POST
def request_export(request):
    """Asking for all my data is a sensitive action: it needs a recent login."""
    member = request.member
    if member is None:
        return redirect("members:join_about")
    row = DataExport.objects.create(member=member)
    enqueue("privacy.export", {"export": row.pk}, dedupe_key=f"privacy.export:{row.pk}")
    messages.success(request, _("We are preparing your data. You will get a notification when it is ready."))
    return redirect("members:my_account")


@assist_never
@login_required
def data_page(request, pk):
    row = get_object_or_404(DataExport, pk=pk, member=request.member)
    ready = row.status == DataExport.READY and row.expires_at and row.expires_at > timezone.now()
    return render(request, "privacy/export.html", {"export": row, "ready": ready})


@assist_never
@sensitive_action
def download(request, pk):
    row = get_object_or_404(DataExport, pk=pk, member=request.member)
    if row.status != DataExport.READY or row.expires_at is None or row.expires_at <= timezone.now():
        raise Http404
    content = export.read_export(row)
    row.downloaded_at = timezone.now()
    row.save(update_fields=["downloaded_at"])
    response = HttpResponse(content, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="unicorn-{request.member.number}.zip"'
    return response
