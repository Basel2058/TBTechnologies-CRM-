"""من يرى ماذا: المدير يرى كل شيء، والموظف يرى العملاء المسندين إليه فقط."""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import Appointment, Customer, Subscription


def customers_for(user):
    qs = Customer.objects.all()
    return qs if user.is_manager else qs.filter(assigned_to=user)


def appointments_for(user):
    qs = Appointment.objects.select_related("customer", "product", "presenter", "customer__assigned_to")
    return qs if user.is_manager else qs.filter(Q(customer__assigned_to=user) | Q(presenter=user))


def subscriptions_for(user):
    qs = Subscription.objects.select_related("customer", "product", "plan", "cancel_reason")
    return qs if user.is_manager else qs.filter(customer__assigned_to=user)


def manager_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_manager:
            raise PermissionDenied("هذه الصفحة للمدير فقط")
        return view(request, *args, **kwargs)

    return wrapper
