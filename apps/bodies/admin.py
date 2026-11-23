from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from . import models

for _model in (
    models.Union,
    models.UnionMembership,
    models.UnionRules,
    models.UnionDelegate,
    models.UnionDecision,
    models.UnionVote,
):
    admin.site.register(_model, ReadOnlyAdmin)
