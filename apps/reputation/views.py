from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from . import services
from .models import Recognition


@login_required
@require_POST
def hide(request, pk):
    """Hide a recognition from the member's own portfolio, or show it again. Only the member's own rows."""
    recognition = get_object_or_404(Recognition, pk=pk, member=request.member)
    services.set_hidden(request.member, recognition, not recognition.hidden_by_owner)
    return redirect("members:portfolio")
