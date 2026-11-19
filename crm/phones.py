"""أدوات أرقام الهاتف: توحيد الصيغة (لكشف التكرار)، العرض، وروابط الاتصال وواتساب.

كل الأرقام تُحفظ بصيغة محلية موحدة مثل 0501234567 حتى نكتشف التكرار مهما كانت
طريقة كتابة الرقم (+972-50-123-4567، 972501234567، 050 123 4567، أو 501234567 من إكسل).
"""

import re
from urllib.parse import quote

from django.conf import settings

LOCAL_COUNTRY_CODES = ("972", "970")


def normalize(raw):
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""

    # أرقام قادمة من إكسل كأرقام عشرية: 501234567.0
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".")[0]
    # صيغة علمية من إكسل: 9.72501E+11
    if re.fullmatch(r"\d+(\.\d+)?[eE]\+?\d+", text):
        try:
            text = str(int(float(text)))
        except ValueError:
            pass

    international = text.startswith("+") or text.startswith("00")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
        international = True

    for code in LOCAL_COUNTRY_CODES:
        if digits.startswith(code) and len(digits) >= len(code) + 8:
            rest = digits[len(code):]
            if rest.startswith("0"):  # +972 (0)50...
                rest = rest[1:]
            return "0" + rest

    if international:
        return "+" + digits

    # إكسل يحذف الصفر في البداية: 501234567 بدل 0501234567
    if not digits.startswith("0") and len(digits) in (8, 9) and digits[0] in "23456789":
        return "0" + digits
    return digits


def display(raw_or_normalized):
    """عرض الرقم بشكل مقروء: 050-123-4567"""
    number = normalize(raw_or_normalized)
    if not number:
        return ""
    if number.startswith("0") and len(number) == 10:
        return f"{number[:3]}-{number[3:6]}-{number[6:]}"
    if number.startswith("0") and len(number) == 9:
        return f"{number[:2]}-{number[2:5]}-{number[5:]}"
    return number


def is_mobile(raw_or_normalized):
    number = normalize(raw_or_normalized)
    return number.startswith("05") and len(number) == 10


def whatsapp_number(raw_or_normalized):
    number = normalize(raw_or_normalized)
    if not number:
        return ""
    if number.startswith("+"):
        return number[1:]
    if number.startswith("0"):
        overrides = settings.TBT.get("PREFIX_COUNTRY_OVERRIDES", {})
        code = overrides.get(number[:3], settings.TBT["DEFAULT_COUNTRY_CODE"])
        return code + number[1:]
    return number


def whatsapp_url(raw_or_normalized, text=""):
    number = whatsapp_number(raw_or_normalized)
    if not number:
        return ""
    url = f"https://wa.me/{number}"
    if text:
        url += "?text=" + quote(text)
    return url


def tel_href(raw_or_normalized):
    number = normalize(raw_or_normalized)
    return f"tel:{number}" if number else ""
