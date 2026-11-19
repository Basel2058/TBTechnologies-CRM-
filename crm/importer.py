"""استيراد قوائم العملاء من Excel أو CSV مع كشف الأرقام المكررة.

الخطوات: رفع الملف ← اختيار ماذا يعني كل عمود (يُخمَّن تلقائياً) ← استيراد وتقرير.
"""

import csv
import io
import re
import uuid
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from . import phones
from .models import Activity, Customer, Sector

MAX_ROWS = 20000

IMPORT_FIELDS = [
    ("", "— تجاهل هذا العمود —"),
    ("business_name", "اسم المصلحة"),
    ("contact_name", "اسم الشخص"),
    ("phone", "الهاتف"),
    ("phone_alt", "هاتف إضافي"),
    ("email", "البريد الإلكتروني"),
    ("city", "المدينة"),
    ("address", "العنوان"),
    ("sector", "نوع المصلحة"),
    ("employees_count", "عدد الموظفين"),
    ("branches_count", "عدد الفروع"),
    ("decision_maker_name", "صاحب القرار"),
    ("decision_maker_phone", "هاتف صاحب القرار"),
    ("competitor_name", "البرنامج الذي يستخدمه"),
    ("quiet_hours", "الوقت الهادئ للاتصال"),
    ("tags", "وسوم"),
    ("notes", "ملاحظات"),
]
FIELD_LABELS = dict(IMPORT_FIELDS)
MULTI_FIELDS = {"notes", "tags"}

# كلمات تساعد في تخمين معنى كل عمود (عربي، عبري، إنجليزي). الترتيب مهم.
KEYWORDS = [
    ("decision_maker_phone", ["هاتف صاحب القرار", "decision maker phone"]),
    ("decision_maker_name", ["صاحب القرار", "مسؤول", "decision", "מקבל החלטות", "בעלים"]),
    ("business_name", ["مصلحة", "المصلحة", "شركة", "الشركة", "محل", "المحل", "business", "company", "עסק", "חברה", "שם העסק"]),
    ("phone_alt", ["هاتف 2", "هاتف إضافي", "هاتف اضافي", "رقم 2", "phone 2", "phone2", "טלפון 2", "טלפון נוסף", "נוסף"]),
    ("phone", ["هاتف", "جوال", "موبايل", "تلفون", "تليفون", "الرقم", "رقم", "phone", "mobile", "tel", "cell", "טלפון", "נייד", "פלאפון"]),
    ("email", ["email", "e-mail", "بريد", "ايميل", "إيميل", "mail", "מייל", "דוא"]),
    ("city", ["مدينة", "المدينة", "البلد", "بلد", "قرية", "city", "town", "עיר", "ישוב", "יישוב"]),
    ("address", ["عنوان", "address", "כתובת"]),
    ("sector", ["نوع", "مجال", "قطاع", "تصنيف", "sector", "category", "industry", "type", "תחום", "סוג", "קטגוריה"]),
    ("employees_count", ["موظفين", "عمال", "employees", "staff", "עובדים"]),
    ("branches_count", ["فروع", "branches", "סניפים"]),
    ("competitor_name", ["برنامج", "منافس", "competitor", "software", "מתחרה", "תוכנה"]),
    ("quiet_hours", ["وقت", "ساعات", "hours", "שעות"]),
    ("notes", ["ملاحظات", "ملاحظة", "notes", "note", "comments", "הערות", "הערה"]),
    ("tags", ["وسوم", "وسم", "tags", "tag", "תגיות"]),
    ("contact_name", ["اسم", "الاسم", "name", "contact", "שם", "איש קשר"]),
]


def import_dir():
    path = Path(settings.MEDIA_ROOT) / "imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(upload):
    token = uuid.uuid4().hex
    suffix = ".csv" if upload.name.lower().endswith(".csv") else ".xlsx"
    with open(import_dir() / f"{token}{suffix}", "wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)
    return token


def path_for(token):
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        return None
    for suffix in (".csv", ".xlsx"):
        path = import_dir() / f"{token}{suffix}"
        if path.exists():
            return path
    return None


def delete_upload(token):
    path = path_for(token)
    if path:
        path.unlink(missing_ok=True)


def _cell_to_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _decode_csv(raw):
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    # ملفات ويندوز القديمة: عربي (1256) أو عبري (1255)
    high = [b for b in raw if b >= 0x80]
    arabic_only = sum(1 for b in high if 0xC1 <= b <= 0xDF)
    encoding = "cp1256" if high and arabic_only > len(high) * 0.1 else "cp1255"
    return raw.decode(encoding, errors="replace")


def read_rows(path):
    path = Path(path)
    if path.suffix == ".csv":
        text = _decode_csv(path.read_bytes())
        try:
            dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = []
        for row in csv.reader(io.StringIO(text), dialect):
            rows.append([cell.strip() for cell in row])
            if len(rows) > MAX_ROWS + 1:
                break
    else:
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append([_cell_to_text(value) for value in row])
            if len(rows) > MAX_ROWS + 1:
                break
        workbook.close()

    rows = [row for row in rows if any(cell for cell in row)]
    width = max((len(row) for row in rows), default=0)
    rows = [row + [""] * (width - len(row)) for row in rows]
    while width and not any(row[width - 1] for row in rows):
        width -= 1
        rows = [row[:width] for row in rows]
    return rows


def _normalize_header(text):
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _looks_like_phone_column(values):
    sample = [v for v in values[:50] if v]
    if not sample:
        return False
    good = sum(1 for v in sample if len(phones.normalize(v)) in (9, 10) and phones.normalize(v).startswith("0"))
    return good >= len(sample) * 0.6


def guess_mapping(headers, sample_rows):
    mapping = [""] * len(headers)
    used = set()
    for field, keywords in KEYWORDS:
        for index, header in enumerate(headers):
            if mapping[index] or (field in used and field not in MULTI_FIELDS):
                continue
            normalized = _normalize_header(header)
            if normalized and any(keyword in normalized for keyword in keywords):
                mapping[index] = field
                used.add(field)
    if "phone" not in used:
        for index in range(len(headers)):
            if not mapping[index] and _looks_like_phone_column([row[index] for row in sample_rows]):
                mapping[index] = "phone"
                break
    return mapping


def _to_int(value):
    digits = re.sub(r"\D", "", value or "")
    return int(digits) if digits and len(digits) < 7 else None


class SectorResolver:
    def __init__(self):
        self.cache = {s.name.strip().lower(): s for s in Sector.objects.all()}

    def get(self, name):
        name = (name or "").strip()[:100]
        if not name:
            return None
        key = name.lower()
        if key not in self.cache:
            self.cache[key] = Sector.objects.create(name=name, order=100)
        return self.cache[key]


def run_import(rows, mapping, *, user, assigned_to=None, product=None, sector=None, source=Customer.Source.IMPORTED,
               tags="", filename="", first_line=2):
    """تُرجع قاموساً فيه: عدد من أُضيفوا، قائمة المكررين، وقائمة الصفوف المرفوضة."""
    existing = {}
    for pk, main, alt in Customer.objects.values_list("pk", "phone_normalized", "phone_alt_normalized"):
        if main:
            existing.setdefault(main, pk)
        if alt:
            existing.setdefault(alt, pk)

    sectors = SectorResolver()
    seen = {}
    to_create, duplicates, invalid = [], [], []
    now = timezone.now()

    for offset, row in enumerate(rows):
        line = first_line + offset
        values = {}
        for index, field in enumerate(mapping):
            if not field or index >= len(row):
                continue
            value = row[index].strip()
            if not value:
                continue
            if field in MULTI_FIELDS and field in values:
                values[field] += (", " if field == "tags" else "\n") + value
            else:
                values[field] = value
        if not values:
            continue

        name = values.get("business_name") or values.get("contact_name") or ""
        main = phones.normalize(values.get("phone"))
        if not main:
            invalid.append({"line": line, "name": name, "problem": "لا يوجد رقم هاتف صحيح"})
            continue
        alt = phones.normalize(values.get("phone_alt"))
        if alt == main:
            alt = ""

        existing_id = existing.get(main) or (existing.get(alt) if alt else None)
        if existing_id:
            duplicates.append({"line": line, "name": name, "phone": phones.display(main), "existing_id": existing_id})
            continue
        if main in seen or (alt and alt in seen):
            duplicates.append({"line": line, "name": name, "phone": phones.display(main), "same_file_line": seen.get(main) or seen.get(alt)})
            continue
        seen[main] = line
        if alt:
            seen[alt] = line

        notes = values.get("notes", "")
        email = values.get("email", "")
        if email:
            try:
                validate_email(email)
            except ValidationError:
                notes = f"{notes}\nبريد: {email}".strip()
                email = ""

        all_tags = ", ".join(t for t in (values.get("tags", ""), tags) if t)
        customer = Customer(
            business_name=values.get("business_name", "")[:200],
            contact_name=values.get("contact_name", "")[:150],
            phone=values["phone"][:30],
            phone_alt=values.get("phone_alt", "")[:30] if alt else "",
            email=email[:254],
            city=values.get("city", "")[:100],
            address=values.get("address", "")[:255],
            sector=sectors.get(values.get("sector")) or sector,
            employees_count=_to_int(values.get("employees_count")),
            branches_count=_to_int(values.get("branches_count")),
            decision_maker_name=values.get("decision_maker_name", "")[:150],
            decision_maker_phone=values.get("decision_maker_phone", "")[:30],
            competitor_name=values.get("competitor_name", "")[:120],
            current_solution=Customer.CurrentSolution.COMPETITOR if values.get("competitor_name") else "",
            quiet_hours=values.get("quiet_hours", "")[:100],
            tags=all_tags[:255],
            notes=notes,
            product=product,
            assigned_to=assigned_to,
            source=source,
            created_by=user,
            created_at=now,
            stage_changed_at=now,
        )
        # bulk_create لا يستدعي save() لذلك نحسب الأرقام الموحدة هنا
        customer.phone_normalized = main
        customer.phone_alt_normalized = alt
        to_create.append(customer)

    with transaction.atomic():
        Customer.objects.bulk_create(to_create, batch_size=500)
        note = f"أُضيف من ملف: {filename}" if filename else "أُضيف من ملف"
        Activity.objects.bulk_create(
            [Activity(customer=c, user=user, kind=Activity.Kind.SYSTEM, text=note, created_at=now) for c in to_create],
            batch_size=500,
        )
    return {"created": len(to_create), "duplicates": duplicates, "invalid": invalid}
