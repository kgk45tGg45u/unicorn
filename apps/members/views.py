from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Member


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
