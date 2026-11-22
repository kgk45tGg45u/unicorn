from django.shortcuts import get_object_or_404, render

from . import services
from .models import Item


def item_page(request, pk):
    item = get_object_or_404(Item, pk=pk)
    return render(request, "catalogue/item.html", {"item": item})


def item_search(request):
    """HTMX endpoint: a list of items matching `q`, used by the recipe editor."""
    return render(request, "catalogue/_item_results.html", {"items": services.find_items(request.GET.get("q", ""))})
