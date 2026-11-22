import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from . import crypto, services
from .models import ContractTemplate, Member, PrivateFile, Signature


@login_required
def my_account(request):
    member = request.member
    if member is None:
        return redirect("core:home")
    missing = []
    if member.status == Member.APPLICANT:
        if member.joined_at is None:
            missing.append("contract")
        missing.append("verification")
    return render(request, "members/my_account.html", {"member": member, "missing": missing})


def public_profile(request, number):
    member = get_object_or_404(Member, number=number, deleted=False)
    return render(request, "members/public_profile.html", {"profile": member})


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
            return redirect("members:my_account")
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
