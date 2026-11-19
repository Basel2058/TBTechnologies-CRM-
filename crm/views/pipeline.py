from datetime import timedelta

from django.db.models import Count, F, Q
from django.shortcuts import render
from django.utils import timezone

from ..models import Customer, Product, Reason, Subscription, User
from ..permissions import customers_for

COLUMN_LIMIT = 60


def pipeline(request):
    customers = customers_for(request.user).select_related("product", "assigned_to", "lost_reason")
    product_id = request.GET.get("product", "")
    agent_id = request.GET.get("agent", "") if request.user.is_manager else ""
    if product_id.isdigit():
        customers = customers.filter(product_id=int(product_id))
    if agent_id.isdigit():
        customers = customers.filter(assigned_to_id=int(agent_id))

    counts = dict(customers.values_list("stage").annotate(n=Count("id")).values_list("stage", "n"))
    columns = []
    for value, label in Customer.Stage.choices:
        items = customers.filter(stage=value).order_by(F("next_call_at").asc(nulls_last=True), "-stage_changed_at")
        shown = list(items[:COLUMN_LIMIT])
        columns.append({
            "value": value,
            "label": label,
            "count": counts.get(value, 0),
            "items": shown,
            "hidden": counts.get(value, 0) - len(shown),
        })
    return render(request, "crm/pipeline.html", {
        "columns": columns,
        "products": Product.objects.all(),
        "agents": User.objects.filter(is_active=True),
        "selected_product": product_id,
        "selected_agent": agent_id,
        "reasons": Reason.objects.filter(kind=Reason.Kind.REJECTION, is_active=True),
        "limit": COLUMN_LIMIT,
    })


def opportunities(request):
    """فرص بيع جاهزة: مشتركون يمكن أن يشتروا تطبيقاً آخر، عقود منافسين تنتهي، وعملاء رفضوا منذ مدة."""
    customers = customers_for(request.user)
    today = timezone.localdate()
    active_products = list(Product.objects.filter(is_active=True))

    subscribers = (
        customers.filter(subscriptions__status=Subscription.Status.ACTIVE)
        .distinct()
        .select_related("assigned_to")
        .prefetch_related("subscriptions__product")
    )
    upsell = []
    for customer in subscribers:
        owned = {s.product_id for s in customer.subscriptions.all() if s.status == Subscription.Status.ACTIVE}
        missing = [p for p in active_products if p.pk not in owned]
        if missing:
            upsell.append({
                "customer": customer,
                "owned": [s.product for s in customer.subscriptions.all() if s.status == Subscription.Status.ACTIVE],
                "missing": missing,
            })

    contracts = (
        customers.filter(contract_end_date__isnull=False, contract_end_date__lte=today + timedelta(days=120),
                         contract_end_date__gte=today - timedelta(days=30))
        .exclude(stage=Customer.Stage.WON)
        .select_related("assigned_to", "product")
        .order_by("contract_end_date")
    )

    reapproach = (
        customers.filter(stage=Customer.Stage.LOST, next_call_at__isnull=True,
                         stage_changed_at__lte=timezone.now() - timedelta(days=90))
        .exclude(last_outcome="wrong_number")
        .exclude(Q(lost_reason__text__contains="أغلق الخط"))
        .select_related("lost_reason", "product", "assigned_to")
        .order_by("stage_changed_at")[:100]
    )

    return render(request, "crm/opportunities.html", {
        "upsell": upsell,
        "contracts": contracts,
        "reapproach": reapproach,
        "today": today,
    })
