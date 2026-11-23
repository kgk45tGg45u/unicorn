from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from . import models

for _model in (models.DataExport, models.DeletionRecord):
    admin.site.register(_model, ReadOnlyAdmin)
