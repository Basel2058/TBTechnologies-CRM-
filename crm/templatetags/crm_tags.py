from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django import template
from django.utils import timezone

from .. import phones
from ..services import ARABIC_WEEKDAYS

register = template.Library()


@register.filter
def smart_dt(value, mode="datetime"):
    """تاريخ مفهوم: «اليوم 14:00»، «غداً 10:00»، «الخميس 13:30»، «23/11 09:00»."""
    if not value:
        return ""
    if isinstance(value, datetime):
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        day, clock = local.date(), local.strftime("%H:%M")
    elif isinstance(value, date):
        day, clock = value, ""
    else:
        return value
    today = timezone.localdate()
    diff = (day - today).days
    if diff == 0:
        label = "اليوم"
    elif diff == 1:
        label = "غداً"
    elif diff == -1:
        label = "أمس"
    elif 1 < diff < 7:
        label = ARABIC_WEEKDAYS[day.weekday()]
    elif day.year == today.year:
        label = f"{ARABIC_WEEKDAYS[day.weekday()]} {day:%d/%m}"
    else:
        label = f"{day:%d/%m/%Y}"
    if mode == "date" or not clock:
        return label
    return f"{label} {clock}"


@register.filter
def weekday(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        value = timezone.localtime(value).date()
    return ARABIC_WEEKDAYS[value.weekday()]


@register.filter
def days_ago(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        value = timezone.localtime(value).date()
    days = (timezone.localdate() - value).days
    if days <= 0:
        return "اليوم"
    if days == 1:
        return "منذ يوم"
    if days == 2:
        return "منذ يومين"
    if days <= 10:
        return f"منذ {days} أيام"
    return f"منذ {days} يوماً"


@register.filter
def phone(value):
    return phones.display(value)


@register.filter
def tel(value):
    return phones.tel_href(value)


@register.filter
def wa(value):
    return phones.whatsapp_url(value)


@register.filter
def money(value):
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    text = f"{amount:,.0f}" if amount == amount.to_integral() else f"{amount:,.2f}"
    return f"{text} ₪"


@register.filter
def percent(part, whole):
    try:
        part, whole = float(part or 0), float(whole or 0)
    except (TypeError, ValueError):
        return 0
    return round(part * 100 / whole) if whole else 0


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def stage_class(value):
    return f"stage-{value}"


@register.filter
def outcome_class(value):
    return f"outcome-{value}"


@register.filter
def appt_class(value):
    return f"appt-{value}"


@register.filter
def is_overdue(value):
    return bool(value and value < timezone.now())


@register.filter
def within_hours(value, hours):
    return bool(value and timezone.now() <= value <= timezone.now() + timedelta(hours=int(hours)))


@register.inclusion_tag("crm/_field.html")
def field(bound_field, wrapper_class=""):
    return {"field": bound_field, "wrapper_class": wrapper_class}


@register.filter
def phone_raw(value):
    return phones.normalize(value)
