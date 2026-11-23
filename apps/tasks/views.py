from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.tickets.models import Ticket

from . import services
from .models import Mandate, Task


@login_required
def task_list(request):
    mine = Task.objects.filter(claimed_by=request.member).exclude(status="confirmed").select_related("ticket")
    open_tasks = Task.objects.filter(status="open", kind="task").select_related("ticket")
    mandates = Mandate.objects.filter(delegate=request.member).select_related("ticket")
    return render(request, "tasks/list.html", {"mine": mine, "open_tasks": open_tasks, "mandates": mandates})


@login_required
def ticket_page(request, number):
    ticket = get_object_or_404(Ticket, number=number)
    applied = ticket.mandate_applications.filter(member=request.member).first()
    return render(
        request,
        "tasks/ticket.html",
        {
            "ticket": ticket,
            "open_for_applications": services.applications_open(ticket),
            "applications": ticket.mandate_applications.count(),
            "applied": applied,
            "mandates": ticket.mandates.select_related("delegate"),
            "tasks": ticket.tasks.select_related("claimed_by"),
            "is_author": ticket.author_id == request.member.pk,
        },
    )


@login_required
@require_POST
def apply(request, number):
    ticket = get_object_or_404(Ticket, number=number)
    try:
        services.apply(ticket, request.member, request.POST.get("statement", ""))
        messages.success(request, _("Thank you. Your application was recorded."))
    except services.TaskError as e:
        messages.error(request, str(e))
    return redirect("tasks:ticket", number=number)


@login_required
@require_POST
def task_action(request, pk, action):
    task = get_object_or_404(Task, pk=pk)
    member = request.member
    try:
        if action == "claim":
            services.claim(task, member)
        elif action == "done":
            services.mark_done(task, member, request.POST.get("evidence", ""))
        elif action == "confirm":
            services.confirm(task, member)
        elif action == "check":
            services.request_random_check(task)
        else:
            raise services.TaskError(_("This is not possible."))
        messages.success(request, _("Done."))
    except services.TaskError as e:
        messages.error(request, str(e))
    return redirect("tasks:ticket", number=task.ticket.number)


@login_required
def mandate_page(request, pk):
    m = get_object_or_404(Mandate.objects.select_related("ticket", "delegate"), pk=pk)
    return render(
        request,
        "tasks/mandate.html",
        {"m": m, "is_delegate": m.delegate_id == request.member.pk, "now": timezone.now()},
    )


@login_required
@require_POST
def mandate_action(request, pk, action):
    m = get_object_or_404(Mandate, pk=pk)
    try:
        if action == "report":
            t = services.report(
                m, request.member, request.POST.get("report", ""), int(request.POST.get("minutes") or 0)
            )
            messages.success(request, _("Your report was sent to be checked."))
            return redirect("tickets:detail", number=t.number)
        if action == "revoke":
            t = services.open_revocation(request.member, m, request.POST.get("reason", ""))
            return redirect("tickets:detail", number=t.number)
        raise services.TaskError(_("This is not possible."))
    except (services.TaskError, ValueError) as e:
        messages.error(request, str(e))
    return redirect("tasks:mandate", pk=pk)
