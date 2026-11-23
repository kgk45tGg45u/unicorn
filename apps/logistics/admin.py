from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from . import models

for _model in (models.PostcodePoint, models.PickupPoint, models.CourierOffer, models.Carrier, models.Shipment):
    admin.site.register(_model, ReadOnlyAdmin)
