from django.apps import AppConfig


class LogisticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.logistics"
    label = "logistics"

    def ready(self):
        from django.db.models.signals import pre_save

        from apps.units.models import Unit

        from . import geo

        def place(sender, instance, **kwargs):
            """When a unit's postcode is saved, its coordinates come from the table (members keep a postcode)."""
            old = Unit.objects.filter(pk=instance.pk).values("postcode", "country").first() if instance.pk else None
            changed = old is None or (old["postcode"], old["country"]) != (instance.postcode, instance.country)
            if changed or instance.lat is None:
                geo.place_unit(instance)

        pre_save.connect(place, sender=Unit, dispatch_uid="logistics.place_unit")

        from apps.market import services as market

        from . import services

        if services.on_line_delivered not in market.DELIVERED_HOOKS:
            market.DELIVERED_HOOKS.append(services.on_line_delivered)
