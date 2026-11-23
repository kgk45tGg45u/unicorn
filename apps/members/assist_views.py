"""Pages for helping a member without a device (P13.T10)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import sensitive_action

from . import assist_services as svc
from .assist import SESSION_KEY, assist_exempt
from .models import AssistConsent, ContractTemplate, Member


def _real(request):
    return request.real_member


def _go_home():
    return redirect("members:assist")


@assist_exempt
@login_required
def home(request):
    me = _real(request)
    if me is None:
        return redirect("members:join_about")
    template = ContractTemplate.objects.filter(kind="assist_consent", is_current=True).first()
    return render(
        request,
        "members/assist.html",
        {
            "me": me,
            "active": svc.active_consents_of(me),
            "open": [c for c in svc.open_consents_of(me) if not svc.is_active(c)],
            "about_me": svc.consents_about(me),
            "to_witness": svc.waiting_for_witness(me),
            "paper_summaries": svc.paper_summaries_for(me),
            "scopes": AssistConsent.SCOPES,
            "template": template,
            "acting_for": request.acting_consent,
        },
    )


@assist_exempt
@login_required
@require_POST
def start(request):
    me = _real(request)
    member = Member.objects.filter(number=request.POST.get("number", "").strip().upper(), deleted=False).first()
    try:
        if member is None:
            raise svc.AssistError(_("There is no member with this number."))
        svc.start(me, member, request.POST.getlist("scopes"), request.POST.get("months") or None)
        messages.success(
            request,
            _("Saved. The person must now sign it, in the app on this device or on paper."),
        )
    except svc.AssistError as e:
        messages.error(request, str(e))
    return _go_home()


@assist_exempt
@sensitive_action
@require_POST
def sign(request, pk):
    consent = get_object_or_404(AssistConsent, pk=pk)
    try:
        svc.sign_in_app(consent, _real(request))
        messages.success(request, _("Thank you. Your helper can now act for you."))
    except svc.AssistError as e:
        messages.error(request, str(e))
    return _go_home()


@assist_exempt
@login_required
@require_POST
def paper(request, pk):
    consent = get_object_or_404(AssistConsent, pk=pk)
    upload = request.FILES.get("scan")
    try:
        if upload is None:
            raise svc.AssistError(_("Please choose the scan of the signed paper."))
        svc.attach_paper(consent, _real(request), upload)
        messages.success(request, _("The paper was added. An identity helper who met the person must now confirm it."))
    except (svc.AssistError, ValueError) as e:
        messages.error(request, str(e))
    return _go_home()


@assist_exempt
@sensitive_action
@require_POST
def witness(request, pk):
    consent = get_object_or_404(AssistConsent, pk=pk)
    try:
        svc.witness_paper(consent, _real(request))
        messages.success(request, _("Thank you. The paper consent is confirmed."))
    except svc.AssistError as e:
        messages.error(request, str(e))
    return _go_home()


@assist_exempt
@login_required
@require_POST
def revoke(request, pk):
    consent = get_object_or_404(AssistConsent, pk=pk)
    try:
        svc.revoke(consent, _real(request))
        if request.session.get(SESSION_KEY) == consent.pk:
            request.session.pop(SESSION_KEY, None)
        messages.success(request, _("The consent has ended."))
    except svc.AssistError as e:
        messages.error(request, str(e))
    return _go_home()


@assist_exempt
@login_required
@require_POST
def act(request, pk):
    consent = svc.consent_for_helper(_real(request), pk)
    if consent is None:
        messages.error(request, _("You cannot act for this person now. The consent may be unsigned or ended."))
        return _go_home()
    request.session[SESSION_KEY] = consent.pk
    return redirect("/")


@assist_exempt
@login_required
@require_POST
def stop(request):
    request.session.pop(SESSION_KEY, None)
    messages.success(request, _("You are no longer acting for anyone."))
    return _go_home()


@login_required
def done_for_me(request):
    return render(request, "members/done_for_me.html", {"events": svc.done_for(request.member)})
