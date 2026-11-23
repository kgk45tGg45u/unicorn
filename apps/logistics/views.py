from django.shortcuts import render

from .models import PickupPoint


def pickup_points(request):
    return render(request, "logistics/pickup_points.html", {"points": PickupPoint.objects.filter(active=True)})
