from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.core.decorators import sensitive_action

from . import services
from .models import Holder


@login_required
@sensitive_action(allow_get=True)
def become_holder(request):
    member = request.member
    if services.is_holder(member):
        return redirect("tradefund:mine")
    template = services.agreement()
    if request.method == "POST":
        if not request.POST.get("accept"):
            messages.error(request, _("Please tick the box to accept the holder agreement."))
        else:
            try:
                services.become_holder(
                    member,
                    request.POST.get("currency") or member.currency,
                    request.POST.get("iban", ""),
                    request.POST.get("bic", ""),
                    request.POST.get("bank_name", ""),
                    separate_account=bool(request.POST.get("separate_account")),
                    iban_shown_to_donors=bool(request.POST.get("iban_shown_to_donors")),
                )
                messages.success(request, _("Thank you. You are now a holder."))
                return redirect("tradefund:mine")
            except services.FundError as e:
                messages.error(request, str(e))
    return render(request, "tradefund/become_holder.html", {"template": template, "currency": member.currency})


@login_required
def my_holding(request):
    holder = Holder.objects.filter(member=request.member).first()
    return render(request, "tradefund/mine.html", {"holder": holder})
