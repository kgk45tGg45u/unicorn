from django.conf import settings


def site(request):
    """What every page's footer shows: where the source code is (HF-19) and which version is running."""
    return {"SOURCE_URL": settings.SOURCE_URL, "UNICORN_VERSION": settings.UNICORN_VERSION}
