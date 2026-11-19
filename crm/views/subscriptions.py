from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from .. import services
from ..forms import CancelSubscriptionForm, SubscriptionForm
from ..models import Activity, Customer, Plan, Product, Subscription
from ..permissions import customers_for, manager_required, subscriptions_for


def subscription_list(request):
    subscriptions = subscriptions_for(request.user)
    status = request.GET.get("status", "active")
    product = request.GET.get("product", "")
    if status in Subscription.Status.values:
        subscriptions = subscriptions.filter(status=status)
    if product.isdigit():
        subscriptions = subscriptions.filter(product_id=int(product))
    active = subscriptions_for(request.user).filter(status=Subscription.Status.ACTIVE)
    return render(request, "crm/subscriptions/list.html", {
        "subscriptions": subscriptions.order_by("-start_date", "-id")[:500],
        "status": status,
        "selected_product": product,
        "products": Product.objects.all(),
        "statuses": Subscription.Status.choices,
        "mrr": active.aggregate(total=Sum("monthly_price"))["total"] or 0,
        "active_count": active.count(),
    })


def subscription_new(request, pk):
    customer = get_object_or_404(customers_for(request.user), pk=pk)
    product = customer.product
    initial = {"product": product.pk if product else None, "monthly_price": product.monthly_price if product else None}
    form = SubscriptionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        subscription = form.save(commit=False)
        subscription.customer = customer
        subscription.created_by = request.user
        subscription.save()
        services.log_activity(
            customer, request.user, Activity.Kind.SUBSCRIPTION,
            f"اشترك في {subscription.product.name} بسعر {subscription.monthly_price:.0f} ₪ شهرياً",
        )
        if subscription.status == Subscription.Status.ACTIVE:
            services.change_stage(customer, Customer.Stage.WON, request.user)
        messages.success(request, "تمت إضافة الاشتراك 🎉")
        return redirect(customer)
    return render(request, "crm/subscriptions/form.html", {
        "form": form, "customer": customer, "plans": Plan.objects.select_related("product"),
        "products": Product.objects.all(), "title": "اشتراك جديد",
    })


@manager_required
def subscription_edit(request, pk):
    subscription = get_object_or_404(Subscription.objects.select_related("customer"), pk=pk)
    form = SubscriptionForm(request.POST or None, instance=subscription)
    if request.method == "POST" and form.is_valid():
        form.save()
        services.log_activity(subscription.customer, request.user, Activity.Kind.SUBSCRIPTION,
                              f"عُدّل اشتراك {subscription.product.name}")
        messages.success(request, "تم حفظ الاشتراك.")
        return redirect(subscription.customer)
    return render(request, "crm/subscriptions/form.html", {
        "form": form, "customer": subscription.customer, "subscription": subscription,
        "plans": Plan.objects.select_related("product"), "products": Product.objects.all(), "title": "تعديل الاشتراك",
    })


@manager_required
def subscription_cancel(request, pk):
    subscription = get_object_or_404(Subscription.objects.select_related("customer", "product"), pk=pk)
    customer = subscription.customer
    if subscription.status == Subscription.Status.CANCELLED:
        messages.info(request, "هذا الاشتراك ملغى مسبقاً.")
        return redirect(customer)
    form = CancelSubscriptionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        subscription.status = Subscription.Status.CANCELLED
        subscription.cancel_reason = data["cancel_reason"]
        subscription.cancel_notes = data["cancel_notes"]
        subscription.cancelled_at = data["cancelled_at"]
        subscription.save()
        text = f"ألغى اشتراك {subscription.product.name} — السبب: {data['cancel_reason'].text}"
        if data["cancel_notes"]:
            text += f" ({data['cancel_notes']})"
        services.log_activity(customer, request.user, Activity.Kind.SUBSCRIPTION, text)
        if not services.has_active_subscription(customer):
            services.change_stage(customer, Customer.Stage.LOST, request.user, note="ألغى الاشتراك")
        messages.success(request, "تم تسجيل إلغاء الاشتراك.")
        return redirect(customer)
    return render(request, "crm/subscriptions/cancel.html", {"form": form, "subscription": subscription})
