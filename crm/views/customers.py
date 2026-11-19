import json
import re
from io import BytesIO

from django.contrib import messages
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font

from .. import phones, services
from ..forms import CustomerFilterForm, CustomerForm, FollowUpForm, NoteForm, StageForm
from ..models import Activity, Customer, MessageTemplate, Product, Reason, Subscription, User
from ..permissions import customers_for, manager_required


def safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


def filter_customers(queryset, form):
    if not form.is_valid():
        return queryset.order_by("-created_at", "-id")
    data = form.cleaned_data
    now = timezone.now()
    query = (data.get("q") or "").strip()
    if query:
        condition = (
            Q(business_name__icontains=query) | Q(contact_name__icontains=query) | Q(city__icontains=query)
            | Q(tags__icontains=query) | Q(email__icontains=query) | Q(decision_maker_name__icontains=query)
        )
        digits = re.sub(r"\D", "", query)
        if len(digits) >= 3:
            condition |= Q(phone_normalized__contains=digits) | Q(phone_alt_normalized__contains=digits)
            normalized = phones.normalize(query)
            if normalized:
                condition |= Q(phone_normalized=normalized) | Q(phone_alt_normalized=normalized)
        queryset = queryset.filter(condition)
    if data.get("stage"):
        queryset = queryset.filter(stage=data["stage"])
    if data.get("product"):
        queryset = queryset.filter(product=data["product"])
    if data.get("sector"):
        queryset = queryset.filter(sector=data["sector"])
    if data.get("city"):
        queryset = queryset.filter(city__icontains=data["city"].strip())
    if data.get("agent"):
        queryset = queryset.filter(assigned_to=data["agent"])
    if data.get("source"):
        queryset = queryset.filter(source=data["source"])
    followup = data.get("followup")
    if followup == "due":
        queryset = queryset.filter(next_call_at__lte=now)
    elif followup == "today":
        queryset = queryset.filter(next_call_at__lte=services.end_of_today(), next_call_at__gte=services.local_dt(timezone.localdate(), 0))
    elif followup == "scheduled":
        queryset = queryset.filter(next_call_at__isnull=False)
    elif followup == "none":
        queryset = queryset.filter(next_call_at__isnull=True)
    active = Subscription.objects.filter(status=Subscription.Status.ACTIVE).values("customer_id")
    if data.get("subscribed") == "yes":
        queryset = queryset.filter(pk__in=active)
    elif data.get("subscribed") == "no":
        queryset = queryset.exclude(pk__in=active)

    order = data.get("order") or "-created_at"
    if order == "next_call_at":
        return queryset.order_by(F("next_call_at").asc(nulls_last=True), "id")
    if order == "-last_call_at":
        return queryset.order_by(F("last_call_at").desc(nulls_last=True), "id")
    if order == "business_name":
        return queryset.order_by("business_name", "contact_name")
    return queryset.order_by("-created_at", "-id")


def customer_list(request):
    from django.core.paginator import Paginator

    form = CustomerFilterForm(request.GET or None, user=request.user)
    queryset = filter_customers(
        customers_for(request.user).select_related("product", "sector", "assigned_to", "lost_reason"), form
    )
    page = Paginator(queryset, 50).get_page(request.GET.get("page"))
    subscribed_ids = set(
        Subscription.objects.filter(customer__in=list(page.object_list), status=Subscription.Status.ACTIVE)
        .values_list("customer_id", flat=True)
    )
    return render(request, "crm/customers/list.html", {
        "form": form,
        "page": page,
        "subscribed_ids": subscribed_ids,
        "filtered": bool(request.GET.dict().keys() - {"page"}),
        "users": User.objects.filter(is_active=True),
        "products": Product.objects.filter(is_active=True),
    })


@require_POST
@manager_required
def customer_bulk(request):
    ids = [int(pk) for pk in request.POST.getlist("ids") if pk.isdigit()]
    action = request.POST.get("action")
    customers = Customer.objects.filter(pk__in=ids)
    back = safe_next(request, reverse("customer_list"))
    if not ids:
        messages.warning(request, "لم تختر أي عميل.")
        return redirect(back)
    if action == "assign":
        agent = User.objects.filter(pk=request.POST.get("agent") or 0, is_active=True).first()
        count = customers.update(assigned_to=agent)
        messages.success(request, f"تم إسناد {count} عميل إلى {agent.display_name if agent else 'لا أحد'}.")
    elif action == "product":
        product = Product.objects.filter(pk=request.POST.get("product") or 0).first()
        count = customers.update(product=product)
        messages.success(request, f"تم تحديد التطبيق لـ {count} عميل.")
    elif action == "queue":
        count = customers.update(next_call_at=timezone.now())
        messages.success(request, f"أُضيف {count} عميل إلى قائمة الاتصال الآن.")
    else:
        messages.error(request, "إجراء غير معروف.")
    return redirect(back)


def customer_create(request):
    user = request.user
    initial = {"phone": request.GET.get("phone", "")}
    if user.is_manager:
        agents = User.objects.filter(is_active=True, role=User.Role.AGENT)
        initial["assigned_to"] = agents.first().pk if agents.count() == 1 else user.pk
    form = CustomerForm(request.POST or None, user=user, initial=initial)
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        customer.created_by = user
        if not user.is_manager:
            customer.assigned_to = user
        if customer.contract_end_date:
            customer.next_call_at = services.contract_followup_at(customer.contract_end_date)
        customer.save()
        services.log_activity(customer, user, Activity.Kind.SYSTEM, "أُضيف العميل")
        messages.success(request, f"تمت إضافة {customer.display_name}.")
        if "call_now" in request.POST:
            return redirect("call", pk=customer.pk)
        return redirect(customer)
    return render(request, "crm/customers/form.html", {"form": form, "title": "عميل جديد"})


def customer_detail(request, pk):
    customer = get_object_or_404(customers_for(request.user).select_related("product", "sector", "assigned_to", "lost_reason"), pk=pk)
    activities = customer.activities.select_related("user", "call", "call__rejection_reason", "call__product", "appointment")[:200]
    appointments = customer.appointments.select_related("product", "presenter").order_by("-scheduled_at")
    subscriptions = customer.subscriptions.select_related("product", "plan", "cancel_reason")
    local_next = timezone.localtime(customer.next_call_at) if customer.next_call_at else None
    return render(request, "crm/customers/detail.html", {
        "customer": customer,
        "activities": activities,
        "appointments": appointments,
        "open_appointments": [a for a in appointments if a.is_open],
        "subscriptions": subscriptions,
        "active_subscriptions": [s for s in subscriptions if s.status == Subscription.Status.ACTIVE],
        "note_form": NoteForm(),
        "followup_form": FollowUpForm(initial={"next_call_at": local_next}),
        "stage_form": StageForm(initial={"stage": customer.stage, "lost_reason": customer.lost_reason_id}),
        "customer_templates": MessageTemplate.objects.filter(is_active=True, context=MessageTemplate.Context.CUSTOMER),
        "appointment_templates": MessageTemplate.objects.filter(is_active=True, context=MessageTemplate.Context.APPOINTMENT),
        "calls_count": customer.calls.count(),
        "whatsapp_phone": best_whatsapp_phone(customer),
    })


def customer_edit(request, pk):
    customer = get_object_or_404(customers_for(request.user), pk=pk)
    old_contract_end = customer.contract_end_date
    form = CustomerForm(request.POST or None, instance=customer, user=request.user)
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        if (
            customer.contract_end_date and customer.contract_end_date != old_contract_end
            and customer.stage != Customer.Stage.WON and not customer.next_call_at
        ):
            customer.next_call_at = services.contract_followup_at(customer.contract_end_date)
            messages.info(request, "سنذكّرك بالاتصال به قبل انتهاء عقده بشهر.")
        customer.save()
        if form.changed_data:
            labels = "، ".join(str(form.fields[name].label) for name in form.changed_data)
            services.log_activity(customer, request.user, Activity.Kind.SYSTEM, f"عُدّلت البيانات: {labels}")
        messages.success(request, "تم حفظ التعديلات.")
        return redirect(customer)
    return render(request, "crm/customers/form.html", {"form": form, "customer": customer, "title": f"تعديل: {customer.display_name}"})


@manager_required
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        name = customer.display_name
        customer.delete()
        messages.success(request, f"تم حذف {name}.")
        return redirect("customer_list")
    return render(request, "crm/confirm_delete.html", {
        "object_name": customer.display_name,
        "warning": "سيتم حذف العميل مع كل مكالماته ومواعيده واشتراكاته. لا يمكن التراجع.",
        "cancel_url": customer.get_absolute_url(),
    })


@require_POST
def customer_note(request, pk):
    customer = get_object_or_404(customers_for(request.user), pk=pk)
    form = NoteForm(request.POST)
    if form.is_valid():
        services.log_activity(customer, request.user, Activity.Kind.NOTE, form.cleaned_data["text"])
        messages.success(request, "أُضيفت الملاحظة.")
    return redirect(safe_next(request, customer.get_absolute_url()))


@require_POST
def customer_followup(request, pk):
    customer = get_object_or_404(customers_for(request.user), pk=pk)
    if request.POST.get("now"):
        when = timezone.now()
        product = Product.objects.filter(pk=request.POST.get("product") or 0).first()
        if product:
            customer.product = product
        text = "أُضيف لقائمة الاتصال الآن" + (f" لعرض {product.name}" if product else "")
    else:
        form = FollowUpForm(request.POST)
        if not form.is_valid():
            messages.error(request, "التاريخ غير صحيح.")
            return redirect(customer)
        when = form.cleaned_data["next_call_at"]
        text = f"حُدد موعد الاتصال القادم: {timezone.localtime(when):%d/%m/%Y %H:%M}" if when else "أُلغي موعد الاتصال القادم"
    customer.next_call_at = when
    customer.save()
    services.log_activity(customer, request.user, Activity.Kind.SYSTEM, text)
    messages.success(request, text)
    return redirect(safe_next(request, customer.get_absolute_url()))


@require_POST
def customer_stage(request, pk):
    customer = get_object_or_404(customers_for(request.user), pk=pk)
    wants_json = request.content_type == "application/json"
    data = json.loads(request.body or "{}") if wants_json else request.POST
    form = StageForm(data)
    if not form.is_valid():
        if wants_json:
            return JsonResponse({"ok": False, "error": "مرحلة غير صحيحة"}, status=400)
        messages.error(request, "مرحلة غير صحيحة.")
        return redirect(customer)
    stage = form.cleaned_data["stage"]
    services.change_stage(customer, stage, request.user, save=False)
    if stage == Customer.Stage.LOST:
        customer.lost_reason = form.cleaned_data.get("lost_reason")
    customer.save()
    needs_subscription = stage == Customer.Stage.WON and not services.has_active_subscription(customer)
    if wants_json:
        return JsonResponse({
            "ok": True,
            "stage": stage,
            "label": customer.get_stage_display(),
            "subscription_url": reverse("subscription_new", args=[customer.pk]) if needs_subscription else "",
        })
    messages.success(request, f"المرحلة الآن: {customer.get_stage_display()}")
    if needs_subscription:
        messages.info(request, "لا تنسَ إضافة الاشتراك حتى يظهر في الإيرادات.")
        return redirect("subscription_new", pk=customer.pk)
    return redirect(safe_next(request, customer.get_absolute_url()))


def best_whatsapp_phone(customer):
    for number in (customer.phone, customer.phone_alt, customer.decision_maker_phone):
        if phones.is_mobile(number):
            return number
    return customer.phone


@require_POST
def customer_whatsapp(request, pk, template_id):
    customer = get_object_or_404(customers_for(request.user), pk=pk)
    template = get_object_or_404(MessageTemplate, pk=template_id, is_active=True)
    text = services.render_message(template.body, customer, request.user)
    services.log_whatsapp(customer, request.user, template)
    return HttpResponseRedirect(phones.whatsapp_url(best_whatsapp_phone(customer), text))


@manager_required
def customer_export(request):
    form = CustomerFilterForm(request.GET or None, user=request.user)
    queryset = filter_customers(Customer.objects.select_related("product", "sector", "assigned_to", "lost_reason"), form)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "العملاء"
    sheet.sheet_view.rightToLeft = True
    headers = [
        "اسم المصلحة", "اسم الشخص", "الهاتف", "هاتف إضافي", "البريد", "المدينة", "العنوان", "نوع المصلحة",
        "التطبيق", "المرحلة", "سبب الرفض", "الموظف", "آخر اتصال", "نتيجة آخر اتصال", "الاتصال القادم",
        "صاحب القرار", "هاتف صاحب القرار", "يستخدم حالياً", "البرنامج المنافس", "انتهاء العقد",
        "عدد الموظفين", "المصدر", "وسوم", "ملاحظات", "تاريخ الإضافة",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    def local(value):
        return timezone.localtime(value).replace(tzinfo=None) if value else None

    for c in queryset.iterator(chunk_size=500):
        sheet.append([
            c.business_name, c.contact_name, phones.display(c.phone), phones.display(c.phone_alt), c.email, c.city,
            c.address, c.sector.name if c.sector else "", c.product.name if c.product else "",
            c.get_stage_display(), c.lost_reason.text if c.lost_reason else "",
            c.assigned_to.display_name if c.assigned_to else "", local(c.last_call_at), c.last_outcome_label,
            local(c.next_call_at), c.decision_maker_name, phones.display(c.decision_maker_phone),
            c.get_current_solution_display() if c.current_solution else "", c.competitor_name, c.contract_end_date,
            c.employees_count, c.get_source_display(), c.tags, c.notes, local(c.created_at),
        ])
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 18
    buffer = BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="tbt-customers-{timezone.localdate():%Y-%m-%d}.xlsx"'
    return response


def reasons_json():
    """أسباب الرفض مع خصائصها (لعرض حقول إضافية في النماذج)."""
    return [
        {"id": r.pk, "text": r.text, "detail": r.requires_detail, "contract": r.asks_contract_end}
        for r in Reason.objects.filter(kind=Reason.Kind.REJECTION, is_active=True)
    ]

