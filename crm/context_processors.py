def crm_context(request):
    """بيانات تظهر في كل الصفحات: أعداد القائمة الجانبية، وتنبيه إرسال واتساب بعد حجز موعد."""
    from django.conf import settings

    data = {"company_name": settings.TBT["COMPANY_NAME"]}
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return data
    from .models import MessageTemplate
    from .permissions import appointments_for, customers_for
    from .services import appointment_buckets, call_queue

    queue = call_queue(customers_for(user))
    buckets = appointment_buckets(appointments_for(user))
    data.update({
        "nav_due_count": queue["due"].count(),
        "nav_appointments_count": buckets["needs_confirmation"].count() + buckets["needs_result"].count(),
    })

    prompt = request.session.pop("whatsapp_prompt", None) if hasattr(request, "session") else None
    if prompt:
        templates = MessageTemplate.objects.filter(is_active=True)
        if prompt.get("appointment"):
            appointment = appointments_for(user).filter(pk=prompt["appointment"]).first()
            if appointment:
                data["wa_prompt"] = {
                    "appointment": appointment,
                    "customer": appointment.customer,
                    "templates": templates.filter(context=MessageTemplate.Context.APPOINTMENT),
                }
        elif prompt.get("customer"):
            customer = customers_for(user).filter(pk=prompt["customer"]).first()
            if customer:
                data["wa_prompt"] = {
                    "customer": customer,
                    "welcome": True,
                    "templates": templates.filter(context=MessageTemplate.Context.CUSTOMER),
                }
    return data
