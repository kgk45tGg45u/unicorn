from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import sensitive_action

from . import services
from .models import Item, Offer, OfferInput, OfferTool, UnitOfMeasure, ValueRun


def item_page(request, pk):
    item = get_object_or_404(Item, pk=pk)
    offers = item.offers.filter(status="active").select_related("unit").order_by("unit__name", "pk")
    return render(request, "catalogue/item.html", {"item": item, "offers": offers})


def item_search(request):
    """HTMX endpoint: a list of items matching `q`, used by the recipe editor."""
    return render(request, "catalogue/_item_results.html", {"items": services.find_items(request.GET.get("q", ""))})


# --- Creating an offer and editing its recipe ---


def _editable_offer(request, pk):
    from apps.units import services as unit_services

    offer = get_object_or_404(Offer.objects.select_related("unit", "item"), pk=pk)
    if not unit_services.can_edit_unit(request.member, offer.unit):
        raise PermissionDenied
    return offer


def _template_id(request):
    return request.POST.get("template") or request.GET.get("template") or ""


def _templates_for(item):
    from apps.bodies.models import RecipeTemplate

    return RecipeTemplate.objects.filter(item=item, union__status="active").select_related("union")


def _union_template(request, item):
    """The union template the member chose ("Start from a union template"), or None."""
    from apps.bodies.models import RecipeTemplate

    chosen = _template_id(request)
    if not chosen:
        return None
    return RecipeTemplate.objects.filter(pk=chosen, item=item, union__status="active").first()


@login_required
def offer_new(request, slug):
    from apps.units.models import Unit

    from .forms import ProductOfferForm, ServiceOfferForm

    unit = get_object_or_404(Unit, slug=slug)
    item = get_object_or_404(Item, pk=request.GET.get("item") or request.POST.get("item"))
    form_class = ProductOfferForm if item.kind == "product" else ServiceOfferForm
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = {k: v for k, v in form.cleaned_data.items() if v not in (None, "")}
        try:
            template = _union_template(request, item)
            if template is not None:
                from apps.bodies import duties

                offer = duties.apply_template(request.member, unit, template, **data)
            else:
                offer = services.create_offer(request.member, unit, item, **data)
        except services.CatalogueError as e:
            form.add_error(None, str(e))
        else:
            return redirect("catalogue:recipe", pk=offer.pk)
    return render(
        request,
        "catalogue/offer_new.html",
        {
            "unit": unit,
            "item": item,
            "form": form,
            "templates": _templates_for(item),
            "template_id": _template_id(request),
        },
    )


@login_required
def recipe_editor(request, pk):
    offer = _editable_offer(request, pk)
    return render(
        request,
        "catalogue/recipe_editor.html",
        {
            "offer": offer,
            "inputs": offer.inputs.select_related("item", "item__uom", "provided_by"),
            "tools": offer.tools.select_related("tool_item"),
            "uoms": UnitOfMeasure.objects.all(),
            "problems": services.validate_recipe(offer),
            "preview": services.preview(offer),
            "switchable": {r.pk for r in offer.inputs.select_related("item") if services.can_switch(r)},
            "workers": [w.member for w in unit_services_workers(offer.unit)],
            "supplier_choices": {},
        },
    )


def unit_services_workers(unit):
    from apps.units import services as unit_services

    return unit_services.workers(unit)


@login_required
@require_POST
def recipe_add_input(request, pk):
    from decimal import Decimal, InvalidOperation

    offer = _editable_offer(request, pk)
    p = request.POST
    try:
        extra = {}
        if p.get("source") == "buy_outside":
            extra["euro_price_estimate"] = Decimal(p.get("euro_price_estimate") or "0")
        if p.get("source") == "own_free":
            extra["provided_by_id"] = int(p.get("provided_by") or 0) or None
        if p.get("source") == "unicorn" and p.get("preferred_supplier"):
            extra["preferred_supplier_id"] = int(p["preferred_supplier"])
        services.add_input(
            request.member,
            offer,
            p.get("name", ""),
            p.get("uom", ""),
            Decimal(p.get("quantity") or "0"),
            p.get("source", ""),
            **extra,
        )
    except (services.CatalogueError, InvalidOperation, ValueError) as e:
        messages.error(request, str(e) if isinstance(e, services.CatalogueError) else _("Please check the numbers."))
    return redirect("catalogue:recipe", pk=pk)


@login_required
@require_POST
def recipe_remove(request, pk, kind, row_pk):
    offer = _editable_offer(request, pk)
    if kind == "input":
        services.remove_input(request.member, get_object_or_404(OfferInput, pk=row_pk, offer=offer))
    else:
        services.remove_tool(request.member, get_object_or_404(OfferTool, pk=row_pk, offer=offer))
    return redirect("catalogue:recipe", pk=pk)


@login_required
@require_POST
def recipe_add_tool(request, pk):
    from decimal import Decimal, InvalidOperation

    offer = _editable_offer(request, pk)
    p = request.POST
    try:
        extra = {}
        if p.get("source") == "own_free":
            extra["provided_by_id"] = int(p.get("provided_by") or 0) or None
        if p.get("source") == "unicorn_owned":
            extra["value_uniq"] = Decimal(p.get("value_uniq") or "0")
            extra["euro_price"] = Decimal(p.get("euro_price") or "0")
        services.add_tool(
            request.member,
            offer,
            p.get("name", ""),
            p.get("source", ""),
            Decimal(p.get("uses_per_batch") or "0"),
            Decimal(p.get("lifetime_uses") or "0"),
            **extra,
        )
    except (services.CatalogueError, InvalidOperation, ValueError) as e:
        messages.error(request, str(e) if isinstance(e, services.CatalogueError) else _("Please check the numbers."))
    return redirect("catalogue:recipe", pk=pk)


@sensitive_action
@require_POST
def recipe_publish(request, pk):
    offer = _editable_offer(request, pk)
    try:
        offer = services.publish_offer(offer, request.member)
        if offer.status == "active":
            messages.success(request, _("The offer is published."))
        else:
            messages.info(request, _("The offer is waiting for random confirmers to look at it."))
    except services.RecipeBlocked as e:
        for m in e.messages:
            messages.error(request, m)
    except services.CatalogueError as e:
        messages.error(request, str(e))
    return redirect("catalogue:recipe", pk=pk)


@login_required
@require_POST
def confirm_free(request, pk):
    row = get_object_or_404(OfferInput, pk=pk)
    try:
        services.confirm_own_free(request.member, row)
        messages.success(request, _("Thank you."))
    except services.CatalogueError as e:
        messages.error(request, str(e))
    return redirect("catalogue:recipe", pk=row.offer_id)


def offer_page(request, pk):
    offer = get_object_or_404(Offer.objects.select_related("unit", "item", "item__uom"), pk=pk)
    member = request.member if request.user.is_authenticated else None
    can_edit = bool(member) and unit_services_can_edit(member, offer.unit)
    if offer.status not in ("active", "value_error", "paused") and not can_edit:
        raise Http404
    return render(
        request,
        "catalogue/offer.html",
        {
            "offer": offer,
            "inputs": offer.inputs.select_related("item", "item__uom"),
            "tools": offer.tools.select_related("tool_item"),
            "lead_time": services.lead_time_days(offer),
            "can_edit": can_edit,
        },
    )


def unit_services_can_edit(member, unit):
    from apps.units import services as unit_services

    return unit_services.can_edit_unit(member, unit)


# --- Open data: the input-output table (no personal data, HF-14) ---


def io_table(request):
    from django.db.models import Sum

    active = Offer.objects.filter(status="active")
    last = ValueRun.objects.order_by("-started_at").first()
    return render(
        request,
        "catalogue/io_table.html",
        {
            "items": Item.objects.exclude(status__in=["placeholder", "retired"]).count(),
            "placeholders": Item.objects.filter(status="placeholder").count(),
            "offers": active.count(),
            "euro_total": active.aggregate(t=Sum("euro_content"))["t"] or 0,
            "last_run": last.finished_at or last.started_at if last else None,
        },
    )


def _csv(name, header, rows):
    import csv

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def io_offers_csv(request):
    rows = (
        (
            o.pk,
            o.unit.slug,
            o.item.name,
            o.item.kind,
            o.item.uom_id,
            o.value_basis,
            o.value_direct,
            o.value_indirect,
            o.value_total,
            o.euro_content,
        )
        for o in Offer.objects.filter(status="active").select_related("unit", "item")
    )
    header = [
        "offer_id",
        "unit",
        "item",
        "kind",
        "uom",
        "basis",
        "direct_hours",
        "indirect_hours",
        "total_hours",
        "euro_content",
    ]
    return _csv("offers", header, rows)


def io_inputs_csv(request):
    rows = (
        (r.offer_id, r.item.name, r.quantity_per_batch, r.source, r.preferred_supplier_id or "")
        for r in OfferInput.objects.filter(offer__status="active").select_related("item")
    )
    return _csv("inputs", ["offer_id", "item", "quantity_per_batch", "source", "preferred_supplier_offer_id"], rows)


def io_tools_csv(request):
    rows = (
        (t.offer_id, t.tool_item.name, t.source, t.uses_per_batch, t.lifetime_uses)
        for t in OfferTool.objects.filter(offer__status="active").select_related("tool_item")
    )
    return _csv("tools", ["offer_id", "tool", "source", "uses_per_batch", "lifetime_uses"], rows)


@login_required
def join_forces(request, slug):
    from apps.units.models import Unit

    from .models import JoinForcesSuggestion

    unit = get_object_or_404(Unit, slug=slug)
    if not unit_services_is_worker(request.member, unit):
        raise PermissionDenied
    if request.method == "POST":
        s = get_object_or_404(JoinForcesSuggestion, pk=request.POST.get("suggestion"))
        try:
            if request.POST.get("answer") == "talk":
                services.start_conversation(request.member, s)
                messages.success(request, _("A decision to talk about it was opened in both units."))
            else:
                services.dismiss_suggestion(request.member, s)
        except services.CatalogueError as e:
            messages.error(request, str(e))
        return redirect("catalogue:join_forces", slug=slug)
    rows = []
    for s in services.suggestions_for_unit(unit):
        if s.status == "new" and unit_services_can_decide(request.member, unit):
            s.status = "seen"
            s.save(update_fields=["status"])
        rows.append((s, services.suggestion_text(s)))
    return render(request, "catalogue/join_forces.html", {"unit": unit, "rows": rows})


def unit_services_is_worker(member, unit):
    from apps.units import services as unit_services

    return unit_services.is_worker(member, unit)


def unit_services_can_decide(member, unit):
    from apps.units import services as unit_services

    return unit_services.can_decide_joins(member, unit)


@login_required
@require_POST
def switch_input(request, pk):
    row = get_object_or_404(OfferInput.objects.select_related("offer__unit", "item"), pk=pk)
    try:
        decision = services.switch_input_source(row, "unicorn", request.member)
        if decision is not None:
            messages.info(request, _("A council decision was opened. The input switches when the council approves."))
        else:
            messages.success(request, _("The input now comes from Unicorn."))
    except services.CatalogueError as e:
        messages.error(request, str(e))
    except unit_services_error() as e:
        messages.error(request, str(e))
    return redirect("catalogue:recipe", pk=row.offer_id)


def unit_services_error():
    from apps.units import services as unit_services

    return unit_services.UnitError
