from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from .. import services
from ..models import Appointment, Call, Customer, Product, Subscription, User
from ..permissions import manager_required
from ..services import ARABIC_WEEKDAYS
from .dashboard import call_stats

PRESETS = [
    ("today", "اليوم"),
    ("7", "آخر 7 أيام"),
    ("month", "هذا الشهر"),
    ("30", "آخر 30 يوماً"),
    ("last_month", "الشهر الماضي"),
    ("90", "آخر 90 يوماً"),
]

LEAD_BUCKETS = [
    (0, 0, "نفس اليوم"),
    (1, 1, "بعد يوم"),
    (2, 3, "بعد 2-3 أيام"),
    (4, 7, "بعد 4-7 أيام"),
    (8, 10_000, "أكثر من أسبوع"),
]


def resolve_range(params):
    today = timezone.localdate()
    try:
        custom_start = date.fromisoformat(params.get("from", ""))
        custom_end = date.fromisoformat(params.get("to", ""))
        if custom_start <= custom_end:
            return "custom", custom_start, custom_end
    except ValueError:
        pass
    preset = params.get("range", "30")
    if preset == "today":
        return preset, today, today
    if preset == "7":
        return preset, today - timedelta(days=6), today
    if preset == "month":
        return preset, today.replace(day=1), today
    if preset == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return preset, end.replace(day=1), end
    if preset == "90":
        return preset, today - timedelta(days=89), today
    return "30", today - timedelta(days=29), today


def bars(rows, total=None):
    """تحضير أشرطة أفقية: الطول نسبة لأكبر قيمة، والنسبة المئوية من المجموع."""
    rows = [r for r in rows if r["value"]]
    peak = max((r["value"] for r in rows), default=0)
    total = total if total is not None else sum(r["value"] for r in rows)
    for row in rows:
        row["width"] = round(row["value"] * 100 / peak, 1) if peak else 0
        row["share"] = round(row["value"] * 100 / total) if total else 0
    return rows


def meters(groups):
    """نسبة الغياب لكل مجموعة: [{label, rate, no_show, total}]"""
    result = []
    for label, (attended, no_show) in groups:
        total = attended + no_show
        if total:
            result.append({"label": label, "rate": round(no_show * 100 / total), "no_show": no_show, "total": total})
    return result


def rate(part, whole):
    return round(part * 100 / whole) if whole else None


@manager_required
def reports(request):
    preset, start, end = resolve_range(request.GET)
    start_dt = services.local_dt(start, 0)
    end_dt = services.local_dt(end + timedelta(days=1), 0)
    agent_id = request.GET.get("agent", "")
    product_id = request.GET.get("product", "")
    agent = User.objects.filter(pk=agent_id).first() if agent_id.isdigit() else None
    product = Product.objects.filter(pk=product_id).first() if product_id.isdigit() else None

    calls = Call.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt)
    if agent:
        calls = calls.filter(agent=agent)
    if product:
        calls = calls.filter(product=product)
    stats = call_stats(calls)

    # --- المكالمات يومياً (أو أسبوعياً لفترة طويلة) ---
    span = (end - start).days + 1
    weekly = span > 45
    per_day = dict(
        calls.annotate(day=TruncDate("created_at")).values("day").annotate(n=Count("id")).values_list("day", "n")
    )
    buckets = defaultdict(int)
    day = start
    while day <= end:
        key = day - timedelta(days=(day.weekday() + 1) % 7) if weekly else day
        buckets[key] += per_day.get(day, 0)
        day += timedelta(days=1)
    peak = max(buckets.values(), default=0)
    timeline = []
    for key in sorted(buckets):
        value = buckets[key]
        label = f"أسبوع {key:%d/%m}" if weekly else f"{ARABIC_WEEKDAYS[key.weekday()]} {key:%d/%m}"
        timeline.append({
            "label": label,
            "short": f"{key:%d/%m}",
            "value": value,
            "height": round(value * 100 / peak, 1) if peak else 0,
            "is_peak": peak and value == peak,
        })

    outcome_labels = dict(Call.Outcome.choices)
    outcomes = bars([
        {"label": outcome_labels.get(row["outcome"], row["outcome"]), "value": row["n"], "key": row["outcome"]}
        for row in calls.values("outcome").annotate(n=Count("id")).order_by("-n")
    ])

    # --- أسباب الرفض ---
    rejections = calls.filter(outcome=Call.Outcome.NOT_INTERESTED)
    rejection_total = rejections.count()
    reasons = bars([
        {"label": row["rejection_reason__text"] or "بدون سبب", "value": row["n"]}
        for row in rejections.values("rejection_reason__text").annotate(n=Count("id")).order_by("-n")
    ], total=rejection_total)
    matrix = None
    product_ids = [pk for pk in rejections.values_list("product_id", flat=True).distinct() if pk]
    if not product and len(product_ids) > 1:
        matrix_products = list(Product.objects.filter(pk__in=product_ids))
        counts = defaultdict(int)
        column_totals = defaultdict(int)
        for reason_text, pid in rejections.values_list("rejection_reason__text", "product_id"):
            if pid:
                counts[(reason_text, pid)] += 1
                column_totals[pid] += 1
        matrix = {
            "products": matrix_products,
            "rows": [
                {
                    "reason": row["label"],
                    "cells": [rate(counts[(row["label"], p.pk)], column_totals[p.pk]) or 0 for p in matrix_products],
                }
                for row in reasons if row["label"] != "بدون سبب"
            ],
            "totals": [column_totals[p.pk] for p in matrix_products],
        }
    details = rejections.exclude(rejection_detail="").select_related("customer", "rejection_reason", "product")[:30]

    # --- المواعيد والغياب ---
    appointments = Appointment.objects.filter(
        scheduled_at__gte=start_dt, scheduled_at__lt=end_dt,
        status__in=[Appointment.Status.ATTENDED, Appointment.Status.NO_SHOW],
    ).select_related("customer__sector")
    if agent:
        appointments = appointments.filter(Q(booked_by=agent) | Q(presenter=agent))
    if product:
        appointments = appointments.filter(product=product)
    by_sector, by_lead, by_type, by_confirm = (defaultdict(lambda: [0, 0]) for _ in range(4))
    type_labels = dict(Appointment.MeetingType.choices)
    attended_total = no_show_total = 0
    for appt in appointments:
        index = 1 if appt.status == Appointment.Status.NO_SHOW else 0
        if index:
            no_show_total += 1
        else:
            attended_total += 1
        by_sector[appt.customer.sector.name if appt.customer.sector else "غير محدد"][index] += 1
        lead = max(appt.lead_days, 0)
        lead_label = next(label for low, high, label in LEAD_BUCKETS if low <= lead <= high)
        by_lead[lead_label][index] += 1
        by_type[type_labels.get(appt.meeting_type, appt.meeting_type)][index] += 1
        by_confirm["أكّد الموعد مسبقاً" if appt.confirmed_at else "لم يؤكّد"][index] += 1
    lead_order = [label for _low, _high, label in LEAD_BUCKETS]
    appointment_report = {
        "total": attended_total + no_show_total,
        "attended": attended_total,
        "no_show": no_show_total,
        "rate": rate(no_show_total, attended_total + no_show_total),
        "by_sector": sorted(meters(by_sector.items()), key=lambda r: -r["total"]),
        "by_lead": meters([(label, by_lead[label]) for label in lead_order if label in by_lead]),
        "by_type": meters(by_type.items()),
        "by_confirm": meters(by_confirm.items()),
    }

    # --- المراحل الآن ---
    customers = Customer.objects.all()
    if agent:
        customers = customers.filter(assigned_to=agent)
    if product:
        customers = customers.filter(product=product)
    stage_counts = dict(customers.values_list("stage").annotate(n=Count("id")).values_list("stage", "n"))
    stages = bars([{"label": label, "value": stage_counts.get(value, 0), "key": value} for value, label in Customer.Stage.choices])

    # --- الإيرادات ---
    subscriptions = Subscription.objects.all()
    if product:
        subscriptions = subscriptions.filter(product=product)
    if agent:
        subscriptions = subscriptions.filter(customer__assigned_to=agent)
    active = subscriptions.filter(status=Subscription.Status.ACTIVE)
    mrr = active.aggregate(total=Sum("monthly_price"))["total"] or 0
    new_subs = subscriptions.filter(start_date__gte=start, start_date__lte=end)
    cancelled = subscriptions.filter(status=Subscription.Status.CANCELLED, cancelled_at__gte=start, cancelled_at__lte=end)
    revenue = {
        "mrr": mrr,
        "active": active.count(),
        "new_count": new_subs.count(),
        "new_mrr": new_subs.aggregate(total=Sum("monthly_price"))["total"] or 0,
        "cancel_count": cancelled.count(),
        "cancel_mrr": cancelled.aggregate(total=Sum("monthly_price"))["total"] or 0,
        "by_product": bars([
            {"label": row["product__name"], "value": float(row["total"] or 0), "count": row["n"]}
            for row in active.values("product__name").annotate(total=Sum("monthly_price"), n=Count("id")).order_by("-total")
        ]),
        "cancel_reasons": bars([
            {"label": row["cancel_reason__text"] or "بدون سبب", "value": row["n"]}
            for row in cancelled.values("cancel_reason__text").annotate(n=Count("id")).order_by("-n")
        ]),
    }

    # --- أداء الموظفين ---
    period = Q(calls__created_at__gte=start_dt, calls__created_at__lt=end_dt)
    if product:
        period &= Q(calls__product=product)
    team = User.objects.annotate(
        total=Count("calls", filter=period),
        answered=Count("calls", filter=period & ~Q(calls__outcome__in=Call.UNANSWERED)),
        demos=Count("calls", filter=period & Q(calls__outcome=Call.Outcome.DEMO_BOOKED)),
        sales=Count("calls", filter=period & Q(calls__outcome=Call.Outcome.SOLD)),
    ).filter(total__gt=0).order_by("-total")
    if agent:
        team = team.filter(pk=agent.pk)

    # --- أي المصالح تشتري أكثر؟ (من تم التواصل معهم) ---
    contacted = customers.filter(last_call_at__isnull=False)
    sector_rows = []
    for row in contacted.values("sector__name").annotate(
        total=Count("id"), won=Count("id", filter=Q(stage=Customer.Stage.WON))
    ).order_by("-total"):
        if row["total"]:
            sector_rows.append({
                "label": row["sector__name"] or "غير محدد", "total": row["total"], "won": row["won"],
                "rate": round(row["won"] * 100 / row["total"]),
            })

    return render(request, "crm/reports.html", {
        "presets": PRESETS,
        "preset": preset,
        "start": start,
        "end": end,
        "agents": User.objects.filter(is_active=True),
        "products": Product.objects.all(),
        "selected_agent": agent_id,
        "selected_product": product_id,
        "stats": stats,
        "answer_rate": rate(stats["answered"], stats["total"]),
        "interest_rate": rate(stats["interested"], stats["answered"]),
        "conversion_rate": rate(stats["sales"], stats["answered"]),
        "timeline": timeline,
        "weekly": weekly,
        "timeline_peak": peak,
        "outcomes": outcomes,
        "reasons": reasons,
        "rejection_total": rejection_total,
        "matrix": matrix,
        "details": details,
        "appointments": appointment_report,
        "stages": stages,
        "revenue": revenue,
        "team": team,
        "sector_rows": sector_rows,
    })
