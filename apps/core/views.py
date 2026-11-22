from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render


def home(request):
    return render(request, "core/home.html")


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
