from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render


def home(request):
    context = {}
    member = getattr(request, "member", None)
    if member is not None:
        from apps.ledger.services import current_period
        from apps.market.models import OrderLine
        from apps.tickets.services import my_open_seats
        from apps.units.services import my_hours_totals

        by_month, _by_unit = my_hours_totals(member)
        key = f"{current_period().year}-{current_period().month:02d}"
        this = next((row for row in by_month if row[0] == key), None)
        context = {
            "month": {"minutes": this[1], "gross": this[2], "tax": this[3], "net": this[4]} if this else None,
            "orders": OrderLine.objects.filter(order__buyer=member).exclude(
                status__in=("delivered", "cancelled", "refused")
            )[:5],
            "seats": my_open_seats(member),
            "my_bodies": _my_bodies(member),
        }
    return render(request, "core/home.html", context)


def _my_bodies(member):
    from apps.bodies.views import my_bodies

    return my_bodies(member)


def offline(request):
    return render(request, "offline.html")


def service_worker(request):
    """Serve sw.js from the site root so it can control every page."""
    js = (Path(settings.BASE_DIR) / "static" / "sw.js").read_text()
    response = HttpResponse(js, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


# --- Legal pages (P14.T07): Markdown files that change only with a release ---

LEGAL_PAGES = {
    "imprint": ("Imprint", "content/legal/imprint.md"),
    "privacy": ("Privacy notice", "content/legal/privacy.md"),
    "terms": ("Terms of use", "content/legal/terms.md"),
    "third-party": ("Third-party notices", "THIRD_PARTY.md"),
}


def legal_page(request, name):
    from django.http import Http404

    from .markdown import render as markdown

    try:
        title, path = LEGAL_PAGES[name]
    except KeyError:
        raise Http404 from None
    text = (Path(settings.BASE_DIR) / path).read_text()
    return render(request, "core/legal.html", {"title": title, "html": markdown(text)})


def server_error(request):
    """The error page shows the request id, so that a member can report it without sending any personal data."""
    from django.http import HttpResponseServerError
    from django.template.loader import render_to_string

    from .logging import current_request_id

    body = render_to_string("500.html", {"request_id": getattr(request, "id", "") or current_request_id()})
    return HttpResponseServerError(body)
