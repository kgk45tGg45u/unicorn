from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render


def home(request):
    return render(request, "home.html")


def offline(request):
    return render(request, "offline.html")


def service_worker(request):
    """Serve sw.js from the site root so it can control every page."""
    js = (Path(settings.BASE_DIR) / "static" / "sw.js").read_text()
    response = HttpResponse(js, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response
