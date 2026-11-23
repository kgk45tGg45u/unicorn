from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from . import models

for _model in (models.ReputationScore, models.SuggestionLog, models.Recognition):
    admin.site.register(_model, ReadOnlyAdmin)
