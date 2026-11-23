from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.tickets.models import Ticket

from . import duties, services
from .models import Union


@login_required
@require_POST
def give_advice(request, number, union_pk):
    ticket = get_object_or_404(Ticket, number=number)
    union = get_object_or_404(Union, pk=union_pk)
    try:
        duties.give_advice(ticket, request.member, union, request.POST.get("body", ""))
        messages.success(request, _("Your advice was added."))
    except (services.BodyError, ValueError) as e:
        messages.error(request, str(e))
    return redirect("tickets:detail", number=number)
