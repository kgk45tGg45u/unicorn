import io
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from . import crypto, services
from .forms import AboutYouForm
from .models import (
    Availability,
    ContractTemplate,
    LaunchClick,
    Licence,
    Member,
    PrivateFile,
    Signature,
    SiteState,
    Skill,
)


@login_required
def my_account(request):
    member = request.member
    if member is None:
        return redirect("members:join_about")
    missing = []
    if member.status == Member.APPLICANT:
        if member.joined_at is None:
            missing.append("contract")
        missing.append("verification")
    return render(
        request,
        "members/my_account.html",
        {
            "member": member,
            "missing": missing,
            "vouches": member.vouches_received.select_related("voucher"),
            "checks": member.checks_received.select_related("helper"),
            **_reputation_context(member),
        },
    )


def _reputation_context(member):
    from apps.reputation import services as reputation

    return {"helpful_count": reputation.helpful_count(member), "my_topics": reputation.my_topics(member)}


def public_profile(request, number):
    member = get_object_or_404(Member, number=number, deleted=False)
    badges = []
    if member.public_profile:
        badges = [
            {"kind": label, "key": key} for key, label in Licence.KINDS if services.has_verified_licence(member, key)
        ]
    from apps.tickets.flags import is_hidden

    hidden = is_hidden("profile", member.pk) and getattr(request, "member", None) != member
    return render(
        request,
        "members/public_profile.html",
        {
            "profile": member,
            "skills": member.skills.all() if member.public_profile else [],
            "badges": badges,
            "hidden": hidden,
        },
    )


def _parts(template):
    """Split the contract body into (title, text) parts at its '## ' headings."""
    parts = []
    for chunk in template.body_md.split("## ")[1:]:
        title, _sep, text = chunk.partition("\n")
        parts.append({"title": title.strip(), "text": text.strip()})
    return parts


@login_required
def contract(request):
    member = request.member
    if member is None:
        return redirect("core:home")
    template = ContractTemplate.objects.filter(kind="membership", is_current=True).first()
    if template is None:
        raise Http404
    parts = _parts(template)
    already = Signature.objects.filter(member=member, template=template).exists()
    error = False
    if request.method == "POST" and not already:
        if all(request.POST.get(f"accept_{i}") for i in range(len(parts))):
            services.sign(member, template, "click")
            messages.success(request, _("Thank you. You have signed the contract."))
            return redirect("members:join_next")
        error = True
    return render(
        request,
        "members/contract.html",
        {"template": template, "parts": parts, "already": already, "error": error},
    )


@login_required
def private_file(request, pk):
    pf = get_object_or_404(PrivateFile, pk=pk)
    if not services.can_view_file(request.member, pf):
        return HttpResponseForbidden(_("You are not allowed to open this file."))
    try:
        name, data = services.read_private_file(pf)
    except crypto.KeyDestroyed:
        raise Http404 from None
    return FileResponse(io.BytesIO(data), as_attachment=True, filename=name, content_type=pf.content_type)


@login_required
def vouch_page(request):
    member = request.member
    if member is None or not services.is_verified(member):
        return HttpResponseForbidden(_("Only verified members can vouch for others."))
    error = None
    if request.method == "POST":
        target = Member.objects.filter(number=request.POST.get("number", "").strip().upper(), deleted=False).first()
        if target is None:
            error = _("We could not find a member with that number.")
        else:
            try:
                services.vouch(member, target, request.POST.get("statement", ""))
            except services.IdentityError as e:
                error = str(e)
            else:
                messages.success(request, _("Thank you. Your vouch is recorded."))
                return redirect("members:vouch")
    return render(request, "members/vouch.html", {"error": error})


@login_required
def identity_check_page(request):
    member = request.member
    if member is None or not (services.is_verified(member) and member.is_identity_helper):
        return HttpResponseForbidden(_("Only identity helpers can record in-person checks."))
    error = None
    if request.method == "POST":
        target = Member.objects.filter(number=request.POST.get("number", "").strip().upper(), deleted=False).first()
        seen_on = parse_date(request.POST.get("seen_on", ""))
        if target is None:
            error = _("We could not find a member with that number.")
        elif seen_on is None:
            error = _("Please enter the date as YYYY-MM-DD.")
        else:
            try:
                services.record_in_person_check(member, target, seen_on, request.POST.get("town", ""))
            except services.IdentityError as e:
                error = str(e)
            else:
                messages.success(request, _("The check is recorded."))
                return redirect("members:identity_check")
    return render(request, "members/identity_check.html", {"error": error})


NOTICE_FOREIGN = gettext_lazy(
    "The laws of your country apply to your work, your sales and the money you hold: "
    "taxes, VAT, labour law and licences. Unicorn starts as a German association, and members abroad are welcome."
)
NOTICE_BENEFITS = gettext_lazy(
    "Income from Unicorn can count against means-tested benefits. We will warn you again when you pass 15 hours a week."
)


@login_required
def join_about(request):
    if request.member is not None:
        return redirect("members:join_next")
    state_trial = services.in_trial_year()
    if state_trial:
        ends = services.trial_ends_at()
        if request.method == "POST" and request.POST.get("waitlist"):
            services.add_to_waitlist(request.user.email)
            messages.success(request, _("You are on the waiting list. We will email you when Unicorn opens."))
            return redirect("core:home")
        return render(request, "members/join_trial.html", {"ends": ends})
    form = AboutYouForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_member_from_about(request.user, form.cleaned_data)
        except services.TooYoung as e:
            form.add_error("birth_date", str(e))
        else:
            return redirect("members:contract")
    return render(request, "members/join_about.html", {"form": form})


@login_required
def join_next(request):
    member = request.member
    if member is None:
        return redirect("members:join_about")
    notices = []
    if member.country != "DE":
        notices.append(NOTICE_FOREIGN)
    if member.receives_benefits:
        notices.append(NOTICE_BENEFITS)
    return render(request, "members/join_next.html", {"member": member, "notices": notices})


@login_required
def launch(request):
    member = request.member
    state = SiteState.get()
    if member is None or not member.is_founder:
        return HttpResponseForbidden(_("Only founders can launch Unicorn."))
    error = None
    if request.method == "POST":
        try:
            state = services.record_launch_click(member)
        except services.IdentityError as e:
            error = str(e)
        else:
            messages.success(request, _("Your click is recorded."))
            return redirect("members:launch")
    return render(
        request,
        "members/launch.html",
        {
            "state": state,
            "error": error,
            "clicked": LaunchClick.objects.filter(member=member).exists(),
            "clicks": LaunchClick.objects.count(),
            "founders": Member.objects.filter(is_founder=True, status=Member.MEMBER).count(),
        },
    )


@login_required
def portfolio(request):
    member = request.member
    if member is None:
        return redirect("members:join_about")
    error = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "skill" and request.POST.get("trade_name", "").strip():
            level = request.POST.get("level", "able")
            Skill.objects.create(
                member=member,
                trade_name=request.POST["trade_name"].strip()[:80],
                trade_code=request.POST.get("trade_code", "").strip()[:16],
                description=request.POST.get("description", ""),
                level=level if level in dict(Skill.LEVELS) else "able",
            )
        elif action == "delete_skill":
            Skill.objects.filter(member=member, pk=request.POST.get("id") or 0).delete()
        elif action == "availability":
            try:
                hours = Decimal(request.POST.get("hours_per_week") or "0")
            except InvalidOperation:
                hours = None
            if hours is None or not (0 <= hours <= 168):
                error = _("Please enter hours per week as a number between 0 and 168.")
            else:
                Availability.objects.update_or_create(
                    member=member, defaults={"hours_per_week": hours, "note": request.POST.get("note", "")[:200]}
                )
        elif action == "public":
            member.public_profile = bool(request.POST.get("public_profile"))
            member.save(update_fields=["public_profile"])
        elif action == "licence":
            upload = request.FILES.get("document")
            kind = request.POST.get("kind")
            if upload is None or kind not in dict(Licence.KINDS):
                error = _("Please choose the kind of licence and a file.")
            else:
                try:
                    services.submit_licence(member, kind, upload, parse_date(request.POST.get("expires_on", "")))
                except services.FileRejected as e:
                    error = str(e)
        if error is None:
            return redirect("members:portfolio")
    return render(
        request,
        "members/portfolio.html",
        {
            "member": member,
            "skills": member.skills.all(),
            "availability": Availability.objects.filter(member=member).first(),
            "licences": member.licences.all(),
            "levels": Skill.LEVELS,
            "licence_kinds": Licence.KINDS,
            "error": error,
        },
    )


@login_required
def leave_page(request):
    member = request.member
    if member is None:
        return redirect("members:join_about")
    reasons = services.leave_blockers(member)
    if request.method == "POST" and request.POST.get("confirm"):
        try:
            services.leave(member)
        except services.LeaveBlocked as e:
            reasons = e.reasons
        else:
            messages.success(request, _("You have left Unicorn. Your UNIQ stay yours and you can still spend them."))
            return redirect("members:my_account")
    return render(request, "members/leave.html", {"member": member, "reasons": reasons})


@login_required
def delete_page(request):
    member = request.member
    if member is None:
        return redirect("members:join_about")
    reasons = services.leave_blockers(member)
    if request.method == "POST" and request.POST.get("confirm"):
        try:
            services.delete_account(member)
        except services.LeaveBlocked as e:
            reasons = e.reasons
        else:
            auth_logout(request)
            messages.success(request, _("Your account is deleted."))
            return redirect("core:home")
    return render(request, "members/delete.html", {"member": member, "reasons": reasons})


@login_required
@require_POST
def mediator_toggle(request):
    """Volunteer for, or leave, the pool of mediators (P06.T09)."""
    member = request.member
    member.is_mediator = not member.is_mediator
    member.save(update_fields=["is_mediator"])
    return redirect("members:my_account")


@login_required
@require_POST
def suggest_toggle(request):
    """Switch "Suggest me for questions" on or off (P13.T08)."""
    from apps.reputation import services as reputation

    reputation.set_suggestions(request.member, not request.member.suggest_me)
    return redirect("members:my_account")


@login_required
@require_POST
def notify_toggle(request):
    """Choose to get every notification by email too (P06.T02)."""
    member = request.member
    member.email_all_notifications = not member.email_all_notifications
    member.save(update_fields=["email_all_notifications"])
    return redirect("members:my_account")
