from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from .. import services
from ..models import Appointment, Call, Customer, Product, Subscription, User
from ..permissions import appointments_for, customers_for


def call_stats(calls):
    return calls.aggregate(
        total=Count("id"),
        answered=Count("id", filter=~Q(outcome__in=Call.UNANSWERED)),
        demos=Count("id", filter=Q(outcome=Call.Outcome.DEMO_BOOKED)),
        sales=Count("id", filter=Q(outcome=Call.Outcome.SOLD)),
        interested=Count("id", filter=Q(outcome__in=[Call.Outcome.INTERESTED, Call.Outcome.DEMO_BOOKED, Call.Outcome.SOLD])),
    )


def dashboard(request):
    user = request.user
    today = timezone.localdate()
    today_start = services.local_dt(today, 0)
    week_start = services.local_dt(today - timedelta(days=6), 0)

    customers = customers_for(user)
    queue = services.call_queue(customers)
    appointments = appointments_for(user)
    buckets = services.appointment_buckets(appointments)

    my_calls = Call.objects.filter(agent=user)
    context = {
        "today": today,
        "due": queue["due"][:8],
        "due_count": queue["due"].count(),
        "later_count": queue["later_today"].count(),
        "new_count": queue["new"].count(),
        "today_appointments": appointments.filter(
            scheduled_at__gte=today_start, scheduled_at__lt=today_start + timedelta(days=1)
        ).exclude(status__in=[Appointment.Status.RESCHEDULED, Appointment.Status.CANCELLED]).order_by("scheduled_at"),
        "needs_confirmation": buckets["needs_confirmation"][:6],
        "needs_confirmation_count": buckets["needs_confirmation"].count(),
        "needs_result": buckets["needs_result"][:6],
        "needs_result_count": buckets["needs_result"].count(),
        "my_today": call_stats(my_calls.filter(created_at__gte=today_start)),
        "my_week": call_stats(my_calls.filter(created_at__gte=week_start)),
    }

    if user.is_manager:
        month_start = services.local_dt(today.replace(day=1), 0)
        active = Subscription.objects.filter(status=Subscription.Status.ACTIVE)
        resolved = Appointment.objects.filter(
            scheduled_at__gte=month_start, status__in=[Appointment.Status.ATTENDED, Appointment.Status.NO_SHOW]
        )
        team = (
            User.objects.filter(is_active=True)
            .annotate(
                # distinct لأن ربط المكالمات والعملاء في نفس الاستعلام يضاعف العدد
                calls_today=Count("calls", filter=Q(calls__created_at__gte=today_start), distinct=True),
                answered_today=Count("calls", filter=Q(calls__created_at__gte=today_start) & ~Q(calls__outcome__in=Call.UNANSWERED), distinct=True),
                demos_today=Count("calls", filter=Q(calls__created_at__gte=today_start, calls__outcome=Call.Outcome.DEMO_BOOKED), distinct=True),
                customers_count=Count("customers", distinct=True),
            )
        )
        context.update({
            "mrr": active.aggregate(total=Sum("monthly_price"))["total"] or 0,
            "active_subscriptions": active.count(),
            "new_this_month": Subscription.objects.filter(start_date__gte=today.replace(day=1)).count(),
            "month_resolved": resolved.count(),
            "month_no_show": resolved.filter(status=Appointment.Status.NO_SHOW).count(),
            "team": [m for m in team if m.calls_today or m.customers_count],
            "team_today": call_stats(Call.objects.filter(created_at__gte=today_start)),
            "setup": {
                "products": Product.objects.exists(),
                "agents": User.objects.filter(role=User.Role.AGENT, is_active=True).exists(),
                "customers": Customer.objects.exists(),
            },
        })
        context["setup_needed"] = not all(context["setup"].values())
    return render(request, "crm/dashboard.html", context)
