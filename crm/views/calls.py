from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .. import services
from ..forms import CallForm
from ..models import Call, MessageTemplate, Objection, Plan, Product, Reason, User
from ..permissions import customers_for

SKIP_KEY = "queue_skip"
AGENT_KEY = "queue_agent"


def scoped_customers(request, agent_param=None):
    """العملاء في قائمة الاتصال. المدير يستطيع اختيار موظف معيّن."""
    customers = customers_for(request.user)
    if request.user.is_manager:
        agent = agent_param if agent_param is not None else request.session.get(AGENT_KEY, "")
        if agent == "me":
            customers = customers.filter(assigned_to=request.user)
        elif agent and str(agent).isdigit():
            customers = customers.filter(assigned_to_id=int(agent))
    return customers


def _skipped(request):
    data = request.session.get(SKIP_KEY) or {}
    if data.get("date") != str(timezone.localdate()):
        return []
    return data.get("ids", [])


def _set_skipped(request, ids):
    request.session[SKIP_KEY] = {"date": str(timezone.localdate()), "ids": ids}


def queue(request):
    agent = request.GET.get("agent", request.session.get(AGENT_KEY, "")) if request.user.is_manager else ""
    if request.user.is_manager:
        request.session[AGENT_KEY] = agent
    sections = services.call_queue(scoped_customers(request, agent))
    return render(request, "crm/queue.html", {
        "due": sections["due"][:300],
        "due_count": sections["due"].count(),
        "later": sections["later_today"],
        "new": sections["new"][:50],
        "new_count": sections["new"].count(),
        "agents": User.objects.filter(is_active=True),
        "selected_agent": agent,
        "skipped_count": len(_skipped(request)),
    })


def queue_next(request):
    """وضع الاتصال المتتالي: يفتح العميل التالي في القائمة مباشرة."""
    skipped = [] if request.GET.get("reset") else _skipped(request)
    skip = request.GET.get("skip", "")
    if skip.isdigit():
        skipped.append(int(skip))
    _set_skipped(request, skipped)
    customer = services.next_in_queue(scoped_customers(request), skipped)
    if customer:
        return redirect(f"{reverse('call', args=[customer.pk])}?mode=queue")
    later = services.call_queue(scoped_customers(request))["later_today"].first()
    if later:
        messages.info(request, f"لا يوجد اتصالات مستحقة الآن 👌 الاتصال التالي الساعة {timezone.localtime(later.next_call_at):%H:%M}.")
    else:
        messages.success(request, "انتهت قائمة الاتصال لليوم 🎉")
    return redirect("queue")


def call_screen(request, pk):
    customer = get_object_or_404(customers_for(request.user).select_related("product", "sector", "lost_reason"), pk=pk)
    queue_mode = request.GET.get("mode") == "queue" or request.POST.get("mode") == "queue"
    form = CallForm(request.POST or None, customer=customer, user=request.user)

    if request.method == "POST" and form.is_valid():
        call, appointment, subscription, info = services.log_call(
            customer=customer, user=request.user, **form.service_kwargs()
        )
        messages.success(request, f"تم تسجيل المكالمة: {call.get_outcome_display()} — {customer.display_name}")
        for line in info:
            messages.info(request, line)
        if appointment:
            request.session["whatsapp_prompt"] = {"appointment": appointment.pk}
        elif subscription:
            request.session["whatsapp_prompt"] = {"customer": customer.pk, "welcome": True}
        if queue_mode:
            return redirect("queue_next")
        return redirect(customer)

    products = Product.objects.filter(Q(is_active=True) | Q(pk=customer.product_id)).prefetch_related("objections")
    queue_left = None
    if queue_mode:
        sections = services.call_queue(scoped_customers(request))
        queue_left = sections["due"].count() + sections["new"].count()

    return render(request, "crm/call.html", {
        "customer": customer,
        "form": form,
        "queue_mode": queue_mode,
        "queue_left": queue_left,
        "recent_calls": customer.calls.select_related("agent", "rejection_reason", "product")[:5],
        "open_appointments": customer.appointments.filter(status__in=["booked", "confirmed"]).order_by("scheduled_at"),
        "products": products,
        "general_objections": Objection.objects.filter(product__isnull=True),
        "reasons": Reason.objects.filter(kind=Reason.Kind.REJECTION, is_active=True),
        "plans": Plan.objects.select_related("product"),
        "outcomes": OUTCOME_TILES,
        "customer_templates": MessageTemplate.objects.filter(is_active=True, context=MessageTemplate.Context.CUSTOMER),
        "users": User.objects.filter(is_active=True),
        "selected_outcome": form["outcome"].value(),
        "max_attempts": services.cfg("MAX_UNANSWERED_ATTEMPTS"),
    })


OUTCOME_TILES = [
    (Call.Outcome.NO_ANSWER, "bi-telephone-x", "tile-muted"),
    (Call.Outcome.BUSY, "bi-hourglass-split", "tile-muted"),
    (Call.Outcome.WRONG_NUMBER, "bi-x-octagon", "tile-danger"),
    (Call.Outcome.CALLBACK, "bi-clock-history", "tile-warning"),
    (Call.Outcome.INFO_REQUESTED, "bi-chat-dots", "tile-warning"),
    (Call.Outcome.INTERESTED, "bi-hand-thumbs-up", "tile-primary"),
    (Call.Outcome.DEMO_BOOKED, "bi-calendar-check", "tile-violet"),
    (Call.Outcome.NOT_INTERESTED, "bi-hand-thumbs-down", "tile-danger"),
    (Call.Outcome.SOLD, "bi-trophy", "tile-success"),
]
