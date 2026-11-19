"""منطق العمل: ماذا يحدث تلقائياً بعد كل مكالمة أو موعد.

القواعد الأساسية:
- لم يرد / مشغول: يعود العميل لقائمة الاتصال تلقائياً (بعد يوم، ثم يومين، ثم 3 أيام)
  وفي وقت مختلف من اليوم. بعد عدد محاولات محدد تتوقف المحاولات.
- اتصل لاحقاً / سأفكر / مهتم: يجب تحديد موعد متابعة.
- غير مهتم: يُسجَّل سبب الرفض. إذا كان عنده برنامج منافس وعرفنا متى ينتهي عقده،
  نتصل به قبل انتهاء العقد بشهر.
- حُجز موعد: يُنشأ موعد وتصبح المرحلة «موعد عرض».
- تم البيع: يُنشأ اشتراك وتصبح المرحلة «مشترك».
- المرحلة تتقدم فقط للأمام (إلا عند الرفض)، والعميل المشترك يبقى «مشترك».
"""

import re
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Activity, Appointment, Call, Customer, Subscription

ARABIC_WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

OUTCOME_TARGET_STAGE = {
    Call.Outcome.CALLBACK: Customer.Stage.CONTACTED,
    Call.Outcome.INFO_REQUESTED: Customer.Stage.CONTACTED,
    Call.Outcome.INTERESTED: Customer.Stage.INTERESTED,
    Call.Outcome.DEMO_BOOKED: Customer.Stage.DEMO,
    Call.Outcome.NOT_INTERESTED: Customer.Stage.LOST,
    Call.Outcome.WRONG_NUMBER: Customer.Stage.LOST,
    Call.Outcome.SOLD: Customer.Stage.WON,
}

FOLLOW_UP_REQUIRED = {Call.Outcome.CALLBACK, Call.Outcome.INFO_REQUESTED, Call.Outcome.INTERESTED}


def cfg(key):
    return settings.TBT[key]


def local_dt(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def end_of_today():
    return local_dt(timezone.localdate(), 23, 59) + timedelta(seconds=59)


def weekday_name(value):
    return ARABIC_WEEKDAYS[timezone.localtime(value).weekday()] if isinstance(value, datetime) else ARABIC_WEEKDAYS[value.weekday()]


def has_active_subscription(customer):
    return customer.subscriptions.filter(status=Subscription.Status.ACTIVE).exists()


def log_activity(customer, user, kind, text, **extra):
    return Activity.objects.create(customer=customer, user=user, kind=kind, text=text, **extra)


def move_forward(current, target):
    """تقدّم المرحلة للأمام فقط. العميل غير المهتم يعود للمسار إذا تجاوب من جديد."""
    if target == Customer.Stage.LOST:
        return target
    if current == Customer.Stage.LOST:
        return target
    order = Customer.STAGE_ORDER
    return target if order.index(target) > order.index(current) else current


def change_stage(customer, new_stage, user=None, note="", save=True):
    if customer.stage == new_stage:
        return False
    old_label = customer.get_stage_display()
    customer.stage = new_stage
    customer.stage_changed_at = timezone.now()
    if new_stage != Customer.Stage.LOST:
        customer.lost_reason = None
    if save:
        customer.save(update_fields=["stage", "stage_changed_at", "lost_reason", "updated_at"])
    text = f"تغيّرت المرحلة من «{old_label}» إلى «{customer.get_stage_display()}»"
    if note:
        text += f" — {note}"
    log_activity(customer, user, Activity.Kind.STAGE, text)
    return True


def retry_time(now, attempts, busy=False):
    """متى نحاول مرة أخرى مع عميل لم يرد."""
    local_now = timezone.localtime(now)
    if busy:
        candidate = local_now + timedelta(hours=2)
        if candidate.hour < 19 and candidate.date() == local_now.date():
            return candidate.replace(second=0, microsecond=0)
        return local_dt(local_now.date() + timedelta(days=1), 10)
    days = 1 if attempts <= 1 else (2 if attempts == 2 else 3)
    # جرّب في وقت مختلف من اليوم: من اتصلنا به صباحاً نجرّبه بعد الظهر والعكس
    hour = 15 if local_now.hour < 13 else 10
    return local_dt(local_now.date() + timedelta(days=days), hour)


def contract_followup_at(end_date):
    target_day = end_date - timedelta(days=cfg("CONTRACT_FOLLOWUP_DAYS_BEFORE"))
    tomorrow = timezone.localdate() + timedelta(days=1)
    return local_dt(max(target_day, tomorrow), 10)


@transaction.atomic
def log_call(*, customer, user, outcome, product=None, notes="", rejection_reason=None,
             rejection_detail="", follow_up_at=None, contract_end_date=None,
             appointment_data=None, subscription_data=None, now=None):
    """تسجيل مكالمة وتطبيق كل القواعد التلقائية. تُرجع (المكالمة، الموعد، الاشتراك، رسائل للمستخدم)."""
    now = now or timezone.now()
    is_subscriber = has_active_subscription(customer)
    product = product or customer.product
    info = []
    appointment = subscription = None

    if outcome != Call.Outcome.NOT_INTERESTED:
        rejection_reason, rejection_detail = None, ""

    call = Call.objects.create(
        customer=customer, agent=user, product=product, outcome=outcome,
        rejection_reason=rejection_reason, rejection_detail=rejection_detail,
        notes=notes, follow_up_at=follow_up_at, created_at=now,
    )

    customer.last_call_at = now
    customer.last_outcome = outcome
    if product and not customer.product_id:
        customer.product = product

    target_stage = customer.stage
    stop_trying = False

    if outcome in (Call.Outcome.NO_ANSWER, Call.Outcome.BUSY):
        customer.unanswered_attempts += 1
        if follow_up_at:
            customer.next_call_at = follow_up_at
        elif customer.unanswered_attempts >= cfg("MAX_UNANSWERED_ATTEMPTS") and not is_subscriber:
            customer.next_call_at = None
            stop_trying = True
            info.append(f"توقفت المحاولات بعد {customer.unanswered_attempts} محاولات بدون رد.")
        else:
            customer.next_call_at = retry_time(now, customer.unanswered_attempts, busy=outcome == Call.Outcome.BUSY)
    else:
        customer.unanswered_attempts = 0
        customer.next_call_at = follow_up_at

    if outcome == Call.Outcome.NOT_INTERESTED and rejection_reason and rejection_reason.asks_contract_end:
        customer.current_solution = Customer.CurrentSolution.COMPETITOR
        if rejection_detail:
            customer.competitor_name = rejection_detail
        if contract_end_date:
            customer.contract_end_date = contract_end_date
            if not follow_up_at:
                customer.next_call_at = contract_followup_at(contract_end_date)
                info.append("سنذكّرك بالاتصال به قبل انتهاء عقده بشهر.")

    if outcome == Call.Outcome.DEMO_BOOKED:
        appointment = Appointment.objects.create(
            customer=customer, product=product, booked_by=user, **(appointment_data or {})
        )

    if outcome == Call.Outcome.SOLD:
        data = dict(subscription_data or {})
        subscription = Subscription.objects.create(
            customer=customer, product=data.pop("product", None) or product, created_by=user, **data
        )

    # --- المرحلة ---
    if outcome == Call.Outcome.SOLD:
        target_stage = Customer.Stage.WON
    elif is_subscriber:
        target_stage = customer.stage  # مكالمات البيع الإضافي لا تغيّر مرحلة المشترك
    elif stop_trying:
        target_stage = Customer.Stage.LOST
    elif outcome in OUTCOME_TARGET_STAGE:
        target_stage = move_forward(customer.stage, OUTCOME_TARGET_STAGE[outcome])

    # --- سجل النشاط ---
    text = f"مكالمة — {call.get_outcome_display()}"
    if product:
        text += f" ({product.name})"
    if rejection_reason:
        text += f"\nسبب الرفض: {rejection_reason.text}"
        if rejection_detail:
            text += f" — {rejection_detail}"
    if notes:
        text += f"\n{notes}"
    log_activity(customer, user, Activity.Kind.CALL, text, call=call, created_at=now)

    if appointment:
        log_activity(
            customer, user, Activity.Kind.APPOINTMENT,
            f"حُجز موعد {appointment.get_meeting_type_display()} يوم {weekday_name(appointment.scheduled_at)} "
            f"{timezone.localtime(appointment.scheduled_at):%d/%m الساعة %H:%M}",
            appointment=appointment,
        )
    if subscription:
        log_activity(
            customer, user, Activity.Kind.SUBSCRIPTION,
            f"اشترك في {subscription.product.name} بسعر {subscription.monthly_price:.0f} ₪ شهرياً",
        )

    stage_note = "بعد عدة محاولات بدون رد" if stop_trying else ""
    change_stage(customer, target_stage, user, note=stage_note, save=False)
    if outcome == Call.Outcome.NOT_INTERESTED and target_stage == Customer.Stage.LOST:
        customer.lost_reason = rejection_reason
    customer.save()
    return call, appointment, subscription, info


# --- قائمة الاتصال ---------------------------------------------------------------

def call_queue(customers):
    """تقسيم العملاء إلى: مستحق الآن، لاحقاً اليوم، وعملاء جدد لم نتصل بهم بعد."""
    now = timezone.now()
    base = customers.select_related("product", "sector", "assigned_to")
    due = base.filter(next_call_at__lte=now).order_by("next_call_at")
    later_today = base.filter(next_call_at__gt=now, next_call_at__lte=end_of_today()).order_by("next_call_at")
    new = base.filter(stage=Customer.Stage.NEW, next_call_at__isnull=True, last_call_at__isnull=True).order_by("created_at", "id")
    return {"due": due, "later_today": later_today, "new": new}


def next_in_queue(customers, skip_ids=()):
    queue = call_queue(customers)
    for key in ("due", "new"):
        customer = queue[key].exclude(pk__in=list(skip_ids)).first()
        if customer:
            return customer
    return None


# --- المواعيد ------------------------------------------------------------------

def book_appointment(customer, user, data):
    appointment = Appointment.objects.create(customer=customer, booked_by=user, **data)
    log_activity(
        customer, user, Activity.Kind.APPOINTMENT,
        f"حُجز موعد {appointment.get_meeting_type_display()} يوم {weekday_name(appointment.scheduled_at)} "
        f"{timezone.localtime(appointment.scheduled_at):%d/%m الساعة %H:%M}",
        appointment=appointment,
    )
    if not has_active_subscription(customer):
        change_stage(customer, move_forward(customer.stage, Customer.Stage.DEMO), user)
    return appointment


def confirm_appointment(appointment, user):
    appointment.status = Appointment.Status.CONFIRMED
    appointment.confirmed_at = timezone.now()
    appointment.save(update_fields=["status", "confirmed_at"])
    log_activity(appointment.customer, user, Activity.Kind.APPOINTMENT, "العميل أكّد الموعد ✅", appointment=appointment)


@transaction.atomic
def mark_attended(appointment, user, outcome_notes="", new_stage="", follow_up_at=None):
    customer = appointment.customer
    appointment.status = Appointment.Status.ATTENDED
    appointment.outcome_notes = outcome_notes
    appointment.save(update_fields=["status", "outcome_notes"])
    text = "حضر الموعد"
    if outcome_notes:
        text += f"\n{outcome_notes}"
    log_activity(customer, user, Activity.Kind.APPOINTMENT, text, appointment=appointment)
    if new_stage:
        change_stage(customer, new_stage, user, save=False)
    if follow_up_at:
        customer.next_call_at = follow_up_at
    customer.save()


@transaction.atomic
def mark_no_show(appointment, user):
    """لم يحضر: اتصل به فوراً. بعد غيابين ينتقل لمتابعة بعد شهر."""
    customer = appointment.customer
    appointment.status = Appointment.Status.NO_SHOW
    appointment.save(update_fields=["status"])
    no_shows = customer.appointments.filter(status=Appointment.Status.NO_SHOW).count()
    log_activity(customer, user, Activity.Kind.APPOINTMENT, f"لم يحضر الموعد (مرة رقم {no_shows})", appointment=appointment)

    if no_shows >= cfg("NO_SHOW_LIMIT"):
        customer.next_call_at = local_dt(timezone.localdate() + timedelta(days=cfg("NO_SHOW_COOLDOWN_DAYS")), 10)
        if customer.stage == Customer.Stage.DEMO:
            change_stage(customer, Customer.Stage.INTERESTED, user, note="غاب عن موعدين", save=False)
        customer.save()
        return f"هذا الغياب رقم {no_shows}. نُقل العميل لمتابعة بعد {cfg('NO_SHOW_COOLDOWN_DAYS')} يوماً."
    customer.next_call_at = timezone.now()
    customer.save(update_fields=["next_call_at", "updated_at"])
    return "اتصل به الآن بلطف: «أكيد انشغلت، بنقدر نعملها هلأ 10 دقايق عالتلفون؟» — وهو الآن في أول قائمة الاتصال."


@transaction.atomic
def reschedule_appointment(appointment, user, data):
    if appointment.is_open:  # موعد «لم يحضر» يبقى كما هو حتى لا نخسر إحصائية الغياب
        appointment.status = Appointment.Status.RESCHEDULED
        appointment.save(update_fields=["status"])
    fields = {
        "product": appointment.product, "meeting_type": appointment.meeting_type, "location": appointment.location,
        "attendees": appointment.attendees, "presenter": appointment.presenter, "notes": appointment.notes,
    }
    fields.update(data)
    new = Appointment.objects.create(customer=appointment.customer, booked_by=user, rescheduled_from=appointment, **fields)
    log_activity(
        appointment.customer, user, Activity.Kind.APPOINTMENT,
        f"تأجّل الموعد إلى يوم {weekday_name(new.scheduled_at)} {timezone.localtime(new.scheduled_at):%d/%m الساعة %H:%M}",
        appointment=new,
    )
    customer = appointment.customer
    if not has_active_subscription(customer):
        change_stage(customer, move_forward(customer.stage, Customer.Stage.DEMO), user)
    return new


def cancel_appointment(appointment, user, note=""):
    appointment.status = Appointment.Status.CANCELLED
    if note:
        appointment.outcome_notes = note
    appointment.save(update_fields=["status", "outcome_notes"])
    text = "أُلغي الموعد" + (f" — {note}" if note else "")
    log_activity(appointment.customer, user, Activity.Kind.APPOINTMENT, text, appointment=appointment)


# --- رسائل واتساب --------------------------------------------------------------

PLACEHOLDERS = [
    ("{الاسم}", "اسم الشخص (أو المصلحة)"),
    ("{المصلحة}", "اسم المصلحة"),
    ("{الموظف}", "اسمك"),
    ("{الشركة}", "اسم الشركة"),
    ("{التطبيق}", "اسم التطبيق"),
    ("{اليوم}", "يوم الموعد (الأحد، الاثنين...)"),
    ("{التاريخ}", "تاريخ الموعد"),
    ("{الوقت}", "ساعة الموعد"),
    ("{نوع_الموعد}", "زيارة / مكالمة فيديو..."),
    ("{المكان}", "عنوان أو رابط الموعد"),
]


def render_message(body, customer, user=None, appointment=None):
    product = (appointment.product if appointment and appointment.product else None) or customer.product
    values = {
        "الاسم": customer.greeting_name,
        "المصلحة": customer.business_name or customer.greeting_name,
        "الموظف": user.short_name if user else "",
        "الشركة": cfg("COMPANY_NAME"),
        "التطبيق": product.name if product else "البرنامج",
    }
    if appointment:
        local = timezone.localtime(appointment.scheduled_at)
        values.update({
            "اليوم": weekday_name(local),
            "التاريخ": local.strftime("%d/%m"),
            "الوقت": local.strftime("%H:%M"),
            "نوع_الموعد": appointment.get_meeting_type_display(),
            "المكان": appointment.location,
        })

    def replace(match):
        key = match.group(1).strip()
        return str(values[key]) if key in values else match.group(0)

    return re.sub(r"\{([^{}]+)\}", replace, body).strip()


def log_whatsapp(customer, user, template, appointment=None):
    log_activity(customer, user, Activity.Kind.WHATSAPP, f"أُرسلت رسالة واتساب: {template.name}", appointment=appointment)
    if appointment:
        appointment.last_whatsapp_at = timezone.now()
        appointment.save(update_fields=["last_whatsapp_at"])


def appointment_buckets(appointments):
    """مواعيد تحتاج تأكيداً (اليوم وغداً) ومواعيد مضت ولم تُسجل نتيجتها."""
    now = timezone.now()
    end_tomorrow = end_of_today() + timedelta(days=1)
    return {
        "needs_confirmation": appointments.filter(
            status=Appointment.Status.BOOKED, scheduled_at__gte=now, scheduled_at__lte=end_tomorrow
        ).order_by("scheduled_at"),
        "needs_result": appointments.filter(
            status__in=Appointment.OPEN_STATUSES, scheduled_at__lt=now - timedelta(minutes=30)
        ).order_by("scheduled_at"),
    }
