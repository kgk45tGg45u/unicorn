from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from . import models

for _model in (
    models.PlanPeriod,
    models.PlanVariant,
    models.BudgetLine,
    models.InvestmentItem,
    models.FocusItem,
    models.ClosureItem,
    models.PlanProposal,
    models.PlanningGroup,
    models.GroupSeat,
    models.ExpertAdviser,
    models.GroupDecision,
    models.PlanComment,
):
    admin.site.register(_model, ReadOnlyAdmin)
