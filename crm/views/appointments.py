from datetime import date, timedelta

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import phones, services
from ..forms import AppointmentForm, AttendedForm, RescheduleForm
from ..models import Appointment, Customer, MessageTemplate
from ..permissions import appointments_for, customers_for
from .customers import best_whatsapp_phone, safe_next


def appointment_templates():
    return MessageTemplate.objects.filter(is_active=True, context=MessageTemplate.Context.APPOINTMENT)


def appointment_list(request):
    appointments = appointments_for(request.user)
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        start = today
    end = start + timedelta(days=7)
    in_range = appointments.filter(
        scheduled_at__gte=services.local_dt(start, 0), scheduled_at__lt=services.local_dt(end, 0)
    ).exclude(status__in=[Appointment.Status.RESCHEDULED, Appointment.Status.CANCELLED]).order_by("scheduled_at")
    by_day = {start + timedelta(days=i): [] for i in range(7)}
    for appointment in in_range:
        by_day.setdefault(timezone.localtime(appointment.scheduled_at).date(), []).append(appointment)

    month_start = services.local_dt(today.replace(day=1), 0)
    resolved = appointments.filter(
        scheduled_at__gte=month_start, status__in=[Appointment.Status.ATTENDED, Appointment.Status.NO_SHOW]
    )
    resolved_count = resolved.count()
    no_show_count = resolved.filter(status=Appointment.Status.NO_SHOW).count()

    return render(request, "crm/appointments/list.html", {
        **services.appointment_buckets(appointments),
        "days": sorted(by_day.items()),
        "start": start,
        "prev_start": start - timedelta(days=7),
        "next_start": end,
        "last_day": end - timedelta(days=1),
        "today": today,
        "templates": appointment_templates(),
        "month_resolved": resolved_count,
        "month_no_show": no_show_count,
    })


def appointment_detail(request, pk):
    appointment = get_object_or_404(appointments_for(request.user), pk=pk)
    history = []
    previous = appointment.rescheduled_from
    while previous and len(history) < 10:
        history.append(previous)
        previous = previous.rescheduled_from
    return render(request, "crm/appointments/detail.html", {
        "appointment": appointment,
        "customer": appointment.customer,
        "templates": appointment_templates(),
        "history": history,
        "next_versions": appointment.rescheduled_to.all(),
        "whatsapp_phone": best_whatsapp_phone(appointment.customer),
    })


def appointment_new(request, pk):
    customer = get_object_or_404(customers_for(request.user), pk=pk)
    form = AppointmentForm(
        request.POST or None,
        initial={"product": customer.product_id, "location": customer.address, "presenter": request.user.pk},
    )
    if request.method == "POST" and form.is_valid():
        data = {field: form.cleaned_data[field] for field in form.Meta.fields}
        appointment = services.book_appointment(customer, request.user, data)
        messages.success(request, "تم حجز الموعد. أرسل تأكيداً بالواتساب الآن 👇")
        request.session["whatsapp_prompt"] = {"appointment": appointment.pk}
        return redirect("appointment_detail", pk=appointment.pk)
    return render(request, "crm/appointments/form.html", {"form": form, "customer": customer, "title": "حجز موعد عرض"})


def appointment_edit(request, pk):
    appointment = get_object_or_404(appointments_for(request.user), pk=pk)
    form = AppointmentForm(request.POST or None, instance=appointment)
    if request.method == "POST" and form.is_valid():
        form.save()
        services.log_activity(appointment.customer, request.user, "appointment", "عُدّلت تفاصيل الموعد", appointment=appointment)
        messages.success(request, "تم حفظ الموعد.")
        return redirect("appointment_detail", pk=appointment.pk)
    return render(request, "crm/appointments/form.html", {
        "form": form, "customer": appointment.customer, "appointment": appointment, "title": "تعديل الموعد",
    })


def _open_appointment(request, pk):
    appointment = get_object_or_404(appointments_for(request.user), pk=pk)
    if not appointment.is_open:
        messages.warning(request, f"هذا الموعد حالته «{appointment.get_status_display()}» ولا يمكن تغييره.")
        return None, redirect("appointment_detail", pk=pk)
    return appointment, None


@require_POST
def appointment_confirm(request, pk):
    appointment, response = _open_appointment(request, pk)
    if response:
        return response
    services.confirm_appointment(appointment, request.user)
    messages.success(request, f"تم تأكيد موعد {appointment.customer.display_name} ✅")
    return redirect(safe_next(request, appointment.get_absolute_url()))


def appointment_attended(request, pk):
    appointment, response = _open_appointment(request, pk)
    if response:
        return response
    form = AttendedForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        services.mark_attended(
            appointment, request.user, outcome_notes=data["outcome_notes"], new_stage=data["new_stage"],
            follow_up_at=data["follow_up_at"],
        )
        messages.success(request, "تم تسجيل حضور الموعد.")
        customer = appointment.customer
        if data["new_stage"] == Customer.Stage.WON and not services.has_active_subscription(customer):
            messages.info(request, "ممتاز! 🎉 أضف الاشتراك الآن حتى يظهر في الإيرادات.")
            return redirect("subscription_new", pk=customer.pk)
        return redirect(customer)
    return render(request, "crm/appointments/attended.html", {"form": form, "appointment": appointment})


@require_POST
def appointment_no_show(request, pk):
    appointment, response = _open_appointment(request, pk)
    if response:
        return response
    message = services.mark_no_show(appointment, request.user)
    messages.warning(request, message)
    return redirect("appointment_detail", pk=pk)


def appointment_reschedule(request, pk):
    appointment = get_object_or_404(appointments_for(request.user), pk=pk)
    if not (appointment.is_open or appointment.status == Appointment.Status.NO_SHOW):
        messages.warning(request, f"هذا الموعد حالته «{appointment.get_status_display()}» ولا يمكن تأجيله.")
        return redirect("appointment_detail", pk=pk)
    local = timezone.localtime(appointment.scheduled_at)
    form = RescheduleForm(request.POST or None, initial={
        "meeting_type": appointment.meeting_type, "location": appointment.location,
        "scheduled_at": local + timedelta(days=1) if appointment.is_past else local,
    })
    if request.method == "POST" and form.is_valid():
        new = services.reschedule_appointment(appointment, request.user, form.cleaned_data)
        messages.success(request, "تم تحديد الموعد الجديد. أرسل تأكيداً بالواتساب 👇")
        request.session["whatsapp_prompt"] = {"appointment": new.pk}
        return redirect("appointment_detail", pk=new.pk)
    return render(request, "crm/appointments/form.html", {
        "form": form, "customer": appointment.customer, "appointment": appointment, "title": "تأجيل الموعد",
    })


@require_POST
def appointment_cancel(request, pk):
    appointment, response = _open_appointment(request, pk)
    if response:
        return response
    services.cancel_appointment(appointment, request.user, request.POST.get("note", "").strip()[:500])
    messages.success(request, "تم إلغاء الموعد.")
    return redirect(appointment.customer)


@require_POST
def appointment_whatsapp(request, pk, template_id):
    appointment = get_object_or_404(appointments_for(request.user), pk=pk)
    template = get_object_or_404(MessageTemplate, pk=template_id, is_active=True)
    customer = appointment.customer
    text = services.render_message(template.body, customer, request.user, appointment=appointment)
    services.log_whatsapp(customer, request.user, template, appointment=appointment)
    return HttpResponseRedirect(phones.whatsapp_url(best_whatsapp_phone(customer), text))
