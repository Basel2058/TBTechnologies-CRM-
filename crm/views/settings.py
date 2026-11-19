from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.db import connection
from django.db.models import Count, ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone

from .. import importer
from ..forms import (
    ImportUploadForm, MessageTemplateForm, ObjectionForm, ReasonForm, SectorForm, StyledSetPasswordForm,
    UserCreateForm, UserEditForm,
)
from ..models import Customer, MessageTemplate, Objection, Product, Reason, Sector, User
from ..permissions import manager_required
from ..services import PLACEHOLDERS


@manager_required
def settings_index(request):
    return render(request, "crm/settings/index.html", {
        "counts": {
            "users": User.objects.filter(is_active=True).count(),
            "reasons": Reason.objects.filter(is_active=True).count(),
            "sectors": Sector.objects.count(),
            "templates": MessageTemplate.objects.filter(is_active=True).count(),
            "objections": Objection.objects.count(),
        }
    })


# --- المستخدمون ----------------------------------------------------------------

@manager_required
def user_list(request):
    users = User.objects.annotate(customers_count=Count("customers")).order_by("-is_active", "first_name", "username")
    return render(request, "crm/settings/users.html", {"users": users})


@manager_required
def user_create(request):
    form = UserCreateForm(request.POST or None, initial={"role": User.Role.AGENT})
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"تم إنشاء حساب {user.display_name}. أعطه اسم الدخول وكلمة المرور.")
        return redirect("user_list")
    return render(request, "crm/settings/form.html", {"form": form, "title": "مستخدم جديد", "back": reverse("user_list")})


@manager_required
def user_edit(request, pk):
    member = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        if member == request.user and (not form.cleaned_data["is_active"] or form.cleaned_data["role"] != User.Role.ADMIN) and not member.is_superuser:
            messages.error(request, "لا يمكنك إيقاف حسابك أو إزالة صلاحية المدير عن نفسك.")
        else:
            member = form.save(commit=False)
            member.is_staff = member.role == User.Role.ADMIN or member.is_superuser
            member.save()
            messages.success(request, "تم حفظ المستخدم.")
            return redirect("user_list")
    return render(request, "crm/settings/form.html", {
        "form": form, "title": f"تعديل: {member.display_name}", "back": reverse("user_list"),
    })


@manager_required
def user_password(request, pk):
    member = get_object_or_404(User, pk=pk)
    form = StyledSetPasswordForm(member, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        if member == request.user:
            update_session_auth_hash(request, member)
        messages.success(request, f"تم تغيير كلمة مرور {member.display_name}.")
        return redirect("user_list")
    return render(request, "crm/settings/form.html", {
        "form": form, "title": f"كلمة مرور جديدة: {member.display_name}", "back": reverse("user_list"),
    })


# --- قوائم بسيطة (الأسباب، أنواع المصالح، قوالب واتساب، الاعتراضات) ----------------------

class SimpleCrud:
    def __init__(self, key, model, form_class, title, singular, columns, help_text="", ordering=None):
        self.key, self.model, self.form_class = key, model, form_class
        self.title, self.singular, self.columns = title, singular, columns
        self.help_text = help_text
        self.ordering = ordering

    def queryset(self):
        qs = self.model.objects.all()
        return qs.order_by(*self.ordering) if self.ordering else qs

    def list_view(self, request):
        rows = []
        for obj in self.queryset():
            cells = []
            for attr, _label in self.columns:
                value = getattr(obj, attr)
                display = getattr(obj, f"get_{attr}_display", None)
                if display:
                    value = display()
                cells.append(value)
            rows.append({"obj": obj, "cells": cells})
        return render(request, "crm/settings/simple_list.html", {
            "crud": self, "rows": rows, "headers": [label for _attr, label in self.columns],
        })

    def form_view(self, request, pk=None):
        obj = get_object_or_404(self.model, pk=pk) if pk else None
        initial = {}
        if not pk and request.GET.get("kind"):
            initial["kind"] = request.GET["kind"]
        form = self.form_class(request.POST or None, instance=obj, initial=initial)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "تم الحفظ.")
            return redirect(f"settings_{self.key}")
        return render(request, "crm/settings/form.html", {
            "form": form,
            "title": f"تعديل {self.singular}" if pk else f"إضافة {self.singular}",
            "back": reverse(f"settings_{self.key}"),
            "placeholders": PLACEHOLDERS if self.model is MessageTemplate else None,
            "delete_url": reverse(f"settings_{self.key}_delete", args=[pk]) if pk else None,
        })

    def delete_view(self, request, pk):
        obj = get_object_or_404(self.model, pk=pk)
        if request.method == "POST":
            try:
                obj.delete()
                messages.success(request, "تم الحذف.")
            except ProtectedError:
                messages.error(request, "لا يمكن الحذف لأنه مستخدم. يمكنك إيقافه بدلاً من ذلك.")
            return redirect(f"settings_{self.key}")
        warning = ""
        if self.model is Reason:
            warning = "إذا كان هذا السبب مستخدماً في مكالمات سابقة فالأفضل إيقافه بدل حذفه، حتى لا تتأثر التقارير."
        return render(request, "crm/confirm_delete.html", {
            "object_name": str(obj), "warning": warning, "cancel_url": reverse(f"settings_{self.key}"),
        })

    def urls(self):
        return [
            path(f"settings/{self.key}/", manager_required(self.list_view), name=f"settings_{self.key}"),
            path(f"settings/{self.key}/new/", manager_required(self.form_view), name=f"settings_{self.key}_new"),
            path(f"settings/{self.key}/<int:pk>/", manager_required(self.form_view), name=f"settings_{self.key}_edit"),
            path(f"settings/{self.key}/<int:pk>/delete/", manager_required(self.delete_view), name=f"settings_{self.key}_delete"),
        ]


CRUDS = [
    SimpleCrud(
        "reasons", Reason, ReasonForm, "أسباب الرفض والإلغاء", "سبب",
        [("text", "السبب"), ("kind", "النوع"), ("requires_detail", "يتطلب تفاصيل"), ("is_active", "فعّال")],
        help_text="هذه القائمة يختار منها الموظف بعد كل رفض أو إلغاء اشتراك، ومنها تُبنى تقارير «لماذا يرفض العملاء».",
        ordering=["kind", "order", "id"],
    ),
    SimpleCrud(
        "sectors", Sector, SectorForm, "أنواع المصالح", "نوع مصلحة",
        [("name", "النوع"), ("order", "الترتيب")],
        help_text="تُستخدم لتصنيف العملاء ولمعرفة أي نوع مصالح يشتري أكثر.",
    ),
    SimpleCrud(
        "templates", MessageTemplate, MessageTemplateForm, "رسائل واتساب الجاهزة", "رسالة",
        [("name", "الاسم"), ("context", "تُستخدم"), ("is_active", "فعّالة")],
        help_text="يضغط الموظف على الرسالة فيفتح واتساب والرسالة جاهزة باسم العميل وموعده — يبقى عليه الضغط على «إرسال».",
    ),
    SimpleCrud(
        "objections", Objection, ObjectionForm, "الردود على الاعتراضات", "رد على اعتراض",
        [("objection", "ماذا يقول العميل"), ("product", "التطبيق")],
        help_text="تظهر للموظف أثناء المكالمة. الردود العامة (بدون تطبيق) تظهر مع كل التطبيقات.",
        ordering=["product__name", "order", "id"],
    ),
]


# --- الاستيراد -----------------------------------------------------------------

@manager_required
def import_upload(request):
    form = ImportUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        token = importer.save_upload(upload)
        try:
            rows = importer.read_rows(importer.path_for(token))
        except Exception:  # ملف تالف أو بصيغة غير مدعومة
            importer.delete_upload(token)
            form.add_error("file", "لم نستطع قراءة الملف. تأكد أنه ملف Excel (.xlsx) أو CSV سليم.")
        else:
            if not rows:
                importer.delete_upload(token)
                form.add_error("file", "الملف فارغ.")
            else:
                data = form.cleaned_data
                request.session[f"import_{token}"] = {
                    "filename": upload.name,
                    "has_header": data["has_header"],
                    "assigned_to": data["assigned_to"].pk if data["assigned_to"] else None,
                    "product": data["product"].pk if data["product"] else None,
                    "sector": data["sector"].pk if data["sector"] else None,
                    "source": data["source"],
                    "tags": data["tags"],
                }
                return redirect("import_map", token=token)
    return render(request, "crm/import/upload.html", {"form": form, "fields": importer.IMPORT_FIELDS[1:]})


@manager_required
def import_map(request, token):
    options = request.session.get(f"import_{token}")
    path_ = importer.path_for(token)
    if not options or not path_:
        messages.error(request, "انتهت صلاحية الملف المرفوع. ارفعه مرة أخرى.")
        return redirect("import_upload")
    rows = importer.read_rows(path_)
    width = len(rows[0]) if rows else 0
    if options["has_header"]:
        headers, data_rows, first_line = rows[0], rows[1:], 2
    else:
        headers, data_rows, first_line = [f"عمود {i + 1}" for i in range(width)], rows, 1
    headers = [h or f"عمود {i + 1}" for i, h in enumerate(headers)]
    truncated = len(data_rows) > importer.MAX_ROWS
    data_rows = data_rows[: importer.MAX_ROWS]

    error = ""
    mapping = importer.guess_mapping(headers, data_rows) if options["has_header"] else importer.guess_mapping([""] * width, data_rows)
    if request.method == "POST":
        valid = {value for value, _label in importer.IMPORT_FIELDS}
        mapping = [request.POST.get(f"col_{i}", "") for i in range(width)]
        mapping = [m if m in valid else "" for m in mapping]
        chosen = [m for m in mapping if m]
        repeated = {m for m in chosen if chosen.count(m) > 1 and m not in importer.MULTI_FIELDS}
        if "phone" not in chosen:
            error = "يجب اختيار عمود «الهاتف»."
        elif repeated:
            error = "اخترت نفس المعنى لأكثر من عمود: " + "، ".join(importer.FIELD_LABELS[m] for m in repeated)
        else:
            result = importer.run_import(
                data_rows, mapping, user=request.user,
                assigned_to=User.objects.filter(pk=options["assigned_to"]).first() if options["assigned_to"] else None,
                product=Product.objects.filter(pk=options["product"]).first() if options["product"] else None,
                sector=Sector.objects.filter(pk=options["sector"]).first() if options["sector"] else None,
                source=options["source"], tags=options["tags"], filename=options["filename"], first_line=first_line,
            )
            importer.delete_upload(token)
            request.session.pop(f"import_{token}", None)
            return render(request, "crm/import/result.html", {"result": result, "filename": options["filename"]})

    columns = []
    for i, header in enumerate(headers):
        columns.append({
            "index": i,
            "header": header,
            "selected": mapping[i] if i < len(mapping) else "",
            "samples": [row[i] for row in data_rows[:4] if i < len(row)],
        })
    return render(request, "crm/import/map.html", {
        "columns": columns,
        "fields": importer.IMPORT_FIELDS,
        "row_count": len(data_rows),
        "truncated": truncated,
        "max_rows": importer.MAX_ROWS,
        "filename": options["filename"],
        "error": error,
        "token": token,
    })


# --- النسخ الاحتياطي ------------------------------------------------------------

@manager_required
def backup_download(request):
    """تنزيل نسخة كاملة من قاعدة البيانات (كل العملاء والمكالمات والمواعيد)."""
    connection.ensure_connection()
    # نسخة متسقة من قاعدة البيانات كما تراها هذه الجلسة (تشمل ملف WAL)
    data = connection.connection.serialize()
    response = HttpResponse(data, content_type="application/x-sqlite3")
    filename = f"tbt-crm-backup-{timezone.localtime():%Y-%m-%d-%H%M}.sqlite3"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@manager_required
def settings_backup(request):
    return render(request, "crm/settings/backup.html", {
        "customers": Customer.objects.count(),
        "db_path": django_settings.DATABASES["default"]["NAME"],
    })
