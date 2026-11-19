from datetime import timedelta

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import SetPasswordForm
from django.db.models import Q
from django.utils import timezone
from django.utils.html import format_html

from . import phones
from .defaults import DEFAULT_CALL_SCRIPT
from .models import (
    Appointment, Call, Customer, MessageTemplate, Objection, Plan, Product, Reason, Sector, Subscription, User,
)
from .services import FOLLOW_UP_REQUIRED


def datetime_widget():
    return forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


def date_widget():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


GRACE = timedelta(minutes=5)


class BootstrapMixin:
    """يضيف أصناف Bootstrap لكل الحقول تلقائياً، ويستبدل «---------» بنص عربي."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, forms.ModelChoiceField) and field.empty_label == "---------":
                field.empty_label = "— اختر —"
            if isinstance(field, forms.TypedChoiceField) or type(field) is forms.ChoiceField:
                field.choices = [(v, "— اختر —" if l == "---------" else l) for v, l in field.choices]
            widget = field.widget
            if isinstance(widget, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)


def ltr(field, inputmode=None):
    field.widget.attrs["dir"] = "ltr"
    if inputmode:
        field.widget.attrs["inputmode"] = inputmode


def active_products(include_id=None):
    query = Q(is_active=True)
    if include_id:
        query |= Q(pk=include_id)
    return Product.objects.filter(query)


# --- العملاء ------------------------------------------------------------------

class CustomerForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "business_name", "contact_name", "phone", "phone_alt", "email", "city", "address", "sector",
            "product", "assigned_to", "source", "language", "employees_count", "branches_count",
            "current_solution", "competitor_name", "contract_end_date", "decision_maker_name",
            "decision_maker_phone", "quiet_hours", "tags", "notes",
        ]
        widgets = {"contract_end_date": date_widget()}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = active_products(self.instance.product_id)
        if user is None or not user.is_manager:
            del self.fields["assigned_to"]
        else:
            self.fields["assigned_to"].queryset = User.objects.filter(is_active=True)
        for name in ("phone", "phone_alt", "decision_maker_phone"):
            ltr(self.fields[name], "tel")
        ltr(self.fields["email"], "email")

    def clean(self):
        data = super().clean()
        if not data.get("business_name") and not data.get("contact_name"):
            raise forms.ValidationError("اكتب اسم المصلحة أو اسم الشخص على الأقل.")
        if data.get("phone") and not phones.normalize(data["phone"]):
            self.add_error("phone", "رقم الهاتف غير صحيح.")
        numbers = [n for n in (phones.normalize(data.get("phone")), phones.normalize(data.get("phone_alt"))) if n]
        if numbers:
            duplicates = Customer.objects.filter(Q(phone_normalized__in=numbers) | Q(phone_alt_normalized__in=numbers))
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            existing = duplicates.select_related("assigned_to").first()
            if existing:
                owner = f" — عند {existing.assigned_to.display_name}" if existing.assigned_to else ""
                self.add_error("phone", format_html(
                    'هذا الرقم مسجّل للعميل <a href="{}">{}</a>{}', existing.get_absolute_url(), existing.display_name, owner
                ))
        return data


class CustomerFilterForm(BootstrapMixin, forms.Form):
    FOLLOWUP_CHOICES = [
        ("", "كل المتابعات"),
        ("due", "مستحق الآن / متأخر"),
        ("today", "اليوم"),
        ("scheduled", "له موعد اتصال قادم"),
        ("none", "بدون موعد اتصال"),
    ]
    ORDER_CHOICES = [
        ("-created_at", "الأحدث إضافة"),
        ("next_call_at", "موعد الاتصال القادم"),
        ("-last_call_at", "آخر اتصال"),
        ("business_name", "الاسم"),
    ]
    q = forms.CharField(label="بحث", required=False)
    stage = forms.ChoiceField(label="المرحلة", required=False, choices=[("", "كل المراحل")] + Customer.Stage.choices)
    product = forms.ModelChoiceField(label="التطبيق", required=False, queryset=Product.objects.all(), empty_label="كل التطبيقات")
    sector = forms.ModelChoiceField(label="نوع المصلحة", required=False, queryset=Sector.objects.all(), empty_label="كل الأنواع")
    city = forms.CharField(label="المدينة", required=False)
    agent = forms.ModelChoiceField(label="الموظف", required=False, queryset=User.objects.all(), empty_label="كل الموظفين")
    source = forms.ChoiceField(label="المصدر", required=False, choices=[("", "كل المصادر")] + Customer.Source.choices)
    followup = forms.ChoiceField(label="الاتصال القادم", required=False, choices=FOLLOWUP_CHOICES)
    subscribed = forms.ChoiceField(
        label="الاشتراك", required=False, choices=[("", "الكل"), ("yes", "مشترك حالياً"), ("no", "غير مشترك")]
    )
    order = forms.ChoiceField(label="الترتيب", required=False, choices=ORDER_CHOICES)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "اسم، هاتف، مدينة، وسم..."
        if user is None or not user.is_manager:
            del self.fields["agent"]


# --- المكالمات -----------------------------------------------------------------

class CallForm(BootstrapMixin, forms.Form):
    outcome = forms.ChoiceField(label="ماذا حصل في المكالمة؟", choices=Call.Outcome.choices, widget=forms.RadioSelect)
    product = forms.ModelChoiceField(label="التطبيق الذي تحدثت عنه", queryset=Product.objects.none(), required=False)
    notes = forms.CharField(
        label="ملاحظات", required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "ماذا قال العميل؟ ما اعتراضاته؟ ماذا يهمه؟"}),
    )
    follow_up_at = forms.DateTimeField(label="متى نتصل به مرة أخرى؟", required=False, widget=datetime_widget())
    rejection_reason = forms.ModelChoiceField(label="سبب الرفض", queryset=Reason.objects.none(), required=False)
    rejection_detail = forms.CharField(label="تفاصيل", required=False, max_length=255)
    contract_end_date = forms.DateField(label="متى ينتهي عقده الحالي؟", required=False, widget=date_widget())
    appt_at = forms.DateTimeField(label="موعد العرض", required=False, widget=datetime_widget())
    appt_type = forms.ChoiceField(label="نوع الموعد", choices=Appointment.MeetingType.choices, required=False)
    appt_location = forms.CharField(label="العنوان أو رابط الاجتماع", required=False, max_length=255)
    appt_attendees = forms.CharField(label="من سيحضر من طرفه؟", required=False, max_length=255)
    appt_presenter = forms.ModelChoiceField(label="من يقدّم العرض؟", queryset=User.objects.filter(is_active=True), required=False)
    sub_plan = forms.ModelChoiceField(label="الباقة", queryset=Plan.objects.select_related("product"), required=False)
    sub_price = forms.DecimalField(label="السعر الشهري (₪)", required=False, min_value=0, max_digits=9, decimal_places=2)
    sub_start = forms.DateField(label="بداية الاشتراك", required=False, widget=date_widget())

    def __init__(self, *args, customer=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = active_products(customer.product_id if customer else None)
        self.fields["rejection_reason"].queryset = Reason.objects.filter(kind=Reason.Kind.REJECTION, is_active=True)
        self.fields["appt_presenter"].initial = user
        self.fields["sub_start"].initial = timezone.localdate()
        self.fields["appt_attendees"].widget.attrs["placeholder"] = "شريك، مدير..."
        ltr(self.fields["sub_price"], "decimal")
        if customer:
            self.fields["product"].initial = customer.product_id
            self.fields["appt_location"].initial = customer.address

    def clean(self):
        data = super().clean()
        outcome = data.get("outcome")
        now = timezone.now()
        follow_up = data.get("follow_up_at")
        if follow_up and follow_up < now - GRACE:
            self.add_error("follow_up_at", "موعد المتابعة يجب أن يكون في المستقبل.")
        if outcome in FOLLOW_UP_REQUIRED and not follow_up:
            self.add_error("follow_up_at", "حدّد يوماً وساعة للاتصال القادم — لا تتركها «بعدين».")

        if outcome == Call.Outcome.NOT_INTERESTED:
            reason = data.get("rejection_reason")
            if not reason:
                self.add_error("rejection_reason", "اختر سبب الرفض — هذا ما يعلّمنا لماذا يرفض العملاء.")
            elif reason.requires_detail and not data.get("rejection_detail"):
                self.add_error("rejection_detail", "اكتب التفاصيل.")

        if outcome == Call.Outcome.DEMO_BOOKED:
            appt_at = data.get("appt_at")
            if not appt_at:
                self.add_error("appt_at", "حدّد يوم وساعة الموعد.")
            elif appt_at < now - GRACE:
                self.add_error("appt_at", "الموعد يجب أن يكون في المستقبل.")
            if not data.get("appt_type"):
                self.add_error("appt_type", "اختر نوع الموعد.")

        if outcome == Call.Outcome.SOLD:
            product, plan = data.get("product"), data.get("sub_plan")
            if not product:
                self.add_error("product", "اختر التطبيق الذي اشترك فيه.")
            if plan and product and plan.product_id != product.pk:
                self.add_error("sub_plan", "هذه الباقة لا تتبع التطبيق المختار.")
            if data.get("sub_price") is None:
                default_price = (plan.monthly_price if plan else None) or (product.monthly_price if product else None)
                if default_price:
                    data["sub_price"] = default_price
                else:
                    self.add_error("sub_price", "اكتب السعر الشهري.")
        return data

    def service_kwargs(self):
        d = self.cleaned_data
        kwargs = {
            "outcome": d["outcome"],
            "product": d.get("product"),
            "notes": d.get("notes", ""),
            "rejection_reason": d.get("rejection_reason"),
            "rejection_detail": d.get("rejection_detail", ""),
            "follow_up_at": d.get("follow_up_at"),
            "contract_end_date": d.get("contract_end_date"),
        }
        if d["outcome"] == Call.Outcome.DEMO_BOOKED:
            kwargs["appointment_data"] = {
                "scheduled_at": d["appt_at"],
                "meeting_type": d["appt_type"],
                "location": d.get("appt_location", ""),
                "attendees": d.get("appt_attendees", ""),
                "presenter": d.get("appt_presenter"),
            }
        if d["outcome"] == Call.Outcome.SOLD:
            kwargs["subscription_data"] = {
                "product": d["product"],
                "plan": d.get("sub_plan"),
                "monthly_price": d["sub_price"],
                "start_date": d.get("sub_start") or timezone.localdate(),
            }
        return kwargs


class NoteForm(BootstrapMixin, forms.Form):
    text = forms.CharField(label="ملاحظة", widget=forms.Textarea(attrs={"rows": 2, "placeholder": "اكتب ملاحظة..."}))


class FollowUpForm(BootstrapMixin, forms.Form):
    next_call_at = forms.DateTimeField(label="الاتصال القادم", required=False, widget=datetime_widget())


class StageForm(BootstrapMixin, forms.Form):
    stage = forms.ChoiceField(label="المرحلة", choices=Customer.Stage.choices)
    lost_reason = forms.ModelChoiceField(
        label="سبب الرفض", required=False, empty_label="— بدون سبب —",
        queryset=Reason.objects.filter(kind=Reason.Kind.REJECTION, is_active=True),
    )


# --- المواعيد ------------------------------------------------------------------

class AppointmentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ["scheduled_at", "meeting_type", "product", "location", "attendees", "presenter", "notes"]
        widgets = {"scheduled_at": datetime_widget()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = active_products(self.instance.product_id)
        self.fields["presenter"].queryset = User.objects.filter(is_active=True)

    def clean_scheduled_at(self):
        value = self.cleaned_data["scheduled_at"]
        if not self.instance.pk and value < timezone.now() - GRACE:
            raise forms.ValidationError("الموعد يجب أن يكون في المستقبل.")
        return value


class RescheduleForm(BootstrapMixin, forms.Form):
    scheduled_at = forms.DateTimeField(label="الموعد الجديد", widget=datetime_widget())
    meeting_type = forms.ChoiceField(label="نوع الموعد", choices=Appointment.MeetingType.choices)
    location = forms.CharField(label="العنوان أو رابط الاجتماع", required=False, max_length=255)

    def clean_scheduled_at(self):
        value = self.cleaned_data["scheduled_at"]
        if value < timezone.now() - GRACE:
            raise forms.ValidationError("الموعد يجب أن يكون في المستقبل.")
        return value


class AttendedForm(BootstrapMixin, forms.Form):
    STAGE_CHOICES = [("", "بدون تغيير")] + [
        (value, label) for value, label in Customer.Stage.choices
        if value in ("interested", "offer", "negotiation", "won", "lost")
    ]
    outcome_notes = forms.CharField(
        label="ماذا حصل في الموعد؟", required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "ما رأيه؟ ماذا طلب؟ ما الخطوة التالية؟"}),
    )
    new_stage = forms.ChoiceField(label="المرحلة الجديدة للعميل", choices=STAGE_CHOICES, required=False)
    follow_up_at = forms.DateTimeField(label="متى نتابع معه؟", required=False, widget=datetime_widget())


# --- الاشتراكات ----------------------------------------------------------------

class SubscriptionForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ["product", "plan", "monthly_price", "start_date", "status", "notes"]
        widgets = {"start_date": date_widget()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = active_products(self.instance.product_id if self.instance.pk else None)
        self.fields["plan"].queryset = Plan.objects.select_related("product")
        self.fields["plan"].required = False
        ltr(self.fields["monthly_price"], "decimal")
        if not self.instance.pk:
            self.fields["status"].choices = [
                c for c in Subscription.Status.choices if c[0] != Subscription.Status.CANCELLED
            ]

    def clean(self):
        data = super().clean()
        product, plan = data.get("product"), data.get("plan")
        if plan and product and plan.product_id != product.pk:
            self.add_error("plan", "هذه الباقة لا تتبع التطبيق المختار.")
        return data


class CancelSubscriptionForm(BootstrapMixin, forms.Form):
    cancel_reason = forms.ModelChoiceField(
        label="لماذا ألغى؟", queryset=Reason.objects.filter(kind=Reason.Kind.CANCELLATION, is_active=True)
    )
    cancel_notes = forms.CharField(label="تفاصيل", required=False, max_length=255)
    cancelled_at = forms.DateField(label="تاريخ الإلغاء", widget=date_widget())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cancelled_at"].initial = timezone.localdate()

    def clean(self):
        data = super().clean()
        reason = data.get("cancel_reason")
        if reason and reason.requires_detail and not data.get("cancel_notes"):
            self.add_error("cancel_notes", "اكتب التفاصيل.")
        return data


# --- التطبيقات والإعدادات --------------------------------------------------------

class ProductForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "description", "target_customers", "monthly_price", "call_script", "is_active", "order"]
        widgets = {"call_script": forms.Textarea(attrs={"rows": 14})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["call_script"].initial = DEFAULT_CALL_SCRIPT
        ltr(self.fields["monthly_price"], "decimal")


class PlanForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["name", "monthly_price", "order"]


PlanFormSet = forms.inlineformset_factory(Product, Plan, form=PlanForm, extra=2, can_delete=True)


class ObjectionForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Objection
        fields = ["product", "objection", "response", "order"]
        widgets = {"response": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].empty_label = "عام — لكل التطبيقات"


class ReasonForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Reason
        fields = ["kind", "text", "requires_detail", "asks_contract_end", "is_active", "order"]


class SectorForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Sector
        fields = ["name", "order"]


class MessageTemplateForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ["name", "context", "body", "is_active", "order"]
        widgets = {"body": forms.Textarea(attrs={"rows": 7})}


class UserCreateForm(BootstrapMixin, forms.ModelForm):
    password1 = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="تأكيد كلمة المرور", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "role"]
        labels = {"username": "اسم الدخول", "first_name": "الاسم الأول", "last_name": "اسم العائلة"}
        help_texts = {"username": "بالأحرف الإنجليزية، بدون مسافات. مثال: ahmad"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ltr(self.fields["username"])

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "كلمتا المرور غير متطابقتين.")
        elif p1:
            try:
                password_validation.validate_password(p1, self.instance)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.is_staff = user.role == User.Role.ADMIN
        if commit:
            user.save()
        return user


class UserEditForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "role", "is_active"]
        labels = {"first_name": "الاسم الأول", "last_name": "اسم العائلة", "is_active": "الحساب فعّال"}
        help_texts = {"is_active": "أوقف الحساب بدل حذفه، حتى يبقى سجل المكالمات محفوظاً."}


class StyledSetPasswordForm(BootstrapMixin, SetPasswordForm):
    pass


# --- الاستيراد -----------------------------------------------------------------

class ImportUploadForm(BootstrapMixin, forms.Form):
    file = forms.FileField(label="ملف العملاء (Excel أو CSV)", widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.xlsm,.csv"}))
    has_header = forms.BooleanField(label="الصف الأول فيه عناوين الأعمدة", required=False, initial=True)
    assigned_to = forms.ModelChoiceField(label="أسند العملاء إلى", queryset=User.objects.filter(is_active=True), required=False, empty_label="بدون إسناد")
    product = forms.ModelChoiceField(label="التطبيق المستهدف", queryset=Product.objects.filter(is_active=True), required=False, empty_label="بدون")
    sector = forms.ModelChoiceField(label="نوع المصلحة (إذا كانت كل القائمة من نوع واحد)", queryset=Sector.objects.all(), required=False, empty_label="حسب الملف")
    source = forms.ChoiceField(label="مصدر القائمة", choices=Customer.Source.choices, initial=Customer.Source.IMPORTED)
    tags = forms.CharField(label="وسم لكل العملاء في هذه القائمة", required=False, max_length=100, help_text="مثلاً: قائمة صالونات حيفا")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        agents = User.objects.filter(is_active=True, role=User.Role.AGENT)
        if agents.count() == 1:
            self.fields["assigned_to"].initial = agents.first().pk

    def clean_file(self):
        upload = self.cleaned_data["file"]
        name = upload.name.lower()
        if not name.endswith((".xlsx", ".xlsm", ".csv")):
            raise forms.ValidationError("الملف يجب أن يكون Excel (.xlsx) أو CSV.")
        if upload.size > 10 * 1024 * 1024:
            raise forms.ValidationError("الملف كبير جداً (الحد 10 ميغابايت).")
        return upload
