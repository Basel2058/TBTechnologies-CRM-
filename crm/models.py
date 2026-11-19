from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.urls import reverse
from django.utils import timezone

from . import phones


class TBTUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "admin")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "مدير"
        AGENT = "agent", "موظف مبيعات"

    role = models.CharField("الدور", max_length=10, choices=Role.choices, default=Role.AGENT)

    objects = TBTUserManager()

    class Meta:
        verbose_name = "مستخدم"
        verbose_name_plural = "المستخدمون"
        ordering = ["first_name", "username"]

    @property
    def is_manager(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def short_name(self):
        return self.first_name or self.username

    def __str__(self):
        return self.display_name


class Sector(models.Model):
    name = models.CharField("نوع المصلحة", max_length=100, unique=True)
    order = models.PositiveIntegerField("الترتيب", default=0)

    class Meta:
        verbose_name = "نوع مصلحة"
        verbose_name_plural = "أنواع المصالح"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    """تطبيق تبيعه الشركة باشتراك شهري."""

    name = models.CharField("اسم التطبيق", max_length=120, unique=True)
    description = models.TextField("ماذا يفعل التطبيق؟", blank=True)
    target_customers = models.CharField("لمن هو؟", max_length=255, blank=True, help_text="مثلاً: صالونات، عيادات، مطاعم")
    monthly_price = models.DecimalField("السعر الشهري الأساسي (₪)", max_digits=9, decimal_places=2, default=Decimal("0"))
    call_script = models.TextField("نص المكالمة", blank=True)
    is_active = models.BooleanField("فعّال (معروض للبيع)", default=True)
    order = models.PositiveIntegerField("الترتيب", default=0)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "تطبيق"
        verbose_name_plural = "التطبيقات"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("product_detail", args=[self.pk])


class Plan(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="plans", verbose_name="التطبيق")
    name = models.CharField("اسم الباقة", max_length=100)
    monthly_price = models.DecimalField("السعر الشهري (₪)", max_digits=9, decimal_places=2)
    order = models.PositiveIntegerField("الترتيب", default=0)

    class Meta:
        verbose_name = "باقة"
        verbose_name_plural = "الباقات"
        ordering = ["order", "monthly_price"]

    def __str__(self):
        return f"{self.product.name} - {self.name}"


class Objection(models.Model):
    """اعتراض شائع والرد المقترح عليه. إذا لم يُحدد تطبيق فهو عام لكل التطبيقات."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, null=True, blank=True, related_name="objections",
        verbose_name="التطبيق", help_text="اتركه فارغاً ليظهر مع كل التطبيقات",
    )
    objection = models.CharField("ماذا يقول العميل؟", max_length=255)
    response = models.TextField("كيف نرد؟")
    order = models.PositiveIntegerField("الترتيب", default=0)

    class Meta:
        verbose_name = "رد على اعتراض"
        verbose_name_plural = "الردود على الاعتراضات"
        ordering = ["order", "id"]

    def __str__(self):
        return self.objection


class Reason(models.Model):
    class Kind(models.TextChoices):
        REJECTION = "rejection", "سبب رفض"
        CANCELLATION = "cancellation", "سبب إلغاء اشتراك"

    kind = models.CharField("النوع", max_length=20, choices=Kind.choices, default=Kind.REJECTION)
    text = models.CharField("السبب", max_length=150)
    requires_detail = models.BooleanField("يجب كتابة تفاصيل", default=False)
    asks_contract_end = models.BooleanField("يسأل عن تاريخ انتهاء عقد المنافس", default=False)
    is_active = models.BooleanField("فعّال", default=True)
    order = models.PositiveIntegerField("الترتيب", default=0)

    class Meta:
        verbose_name = "سبب"
        verbose_name_plural = "الأسباب"
        ordering = ["kind", "order", "id"]
        constraints = [models.UniqueConstraint(fields=["kind", "text"], name="unique_reason_per_kind")]

    def __str__(self):
        return self.text


class MessageTemplate(models.Model):
    class Context(models.TextChoices):
        APPOINTMENT = "appointment", "للمواعيد"
        CUSTOMER = "customer", "عامة للعملاء"

    name = models.CharField("اسم الرسالة", max_length=100)
    context = models.CharField("تُستخدم", max_length=20, choices=Context.choices, default=Context.CUSTOMER)
    body = models.TextField("نص الرسالة")
    is_active = models.BooleanField("فعّالة", default=True)
    order = models.PositiveIntegerField("الترتيب", default=0)

    class Meta:
        verbose_name = "قالب واتساب"
        verbose_name_plural = "قوالب واتساب"
        ordering = ["context", "order", "id"]

    def __str__(self):
        return self.name


class Customer(models.Model):
    class Stage(models.TextChoices):
        NEW = "new", "جديد"
        CONTACTED = "contacted", "تم التواصل"
        INTERESTED = "interested", "مهتم"
        DEMO = "demo", "موعد عرض"
        OFFER = "offer", "عرض سعر"
        NEGOTIATION = "negotiation", "تفاوض"
        WON = "won", "مشترك"
        LOST = "lost", "غير مهتم"

    # ترتيب التقدم في البيع (غير مهتم خارج الترتيب)
    STAGE_ORDER = ["new", "contacted", "interested", "demo", "offer", "negotiation", "won"]

    class Source(models.TextChoices):
        IMPORTED = "imported", "قائمة مستوردة"
        AD = "ad", "إعلان"
        REFERRAL = "referral", "توصية"
        WEBSITE = "website", "موقع / سوشال ميديا"
        FIELD = "field", "زيارة ميدانية"
        INBOUND = "inbound", "تواصل معنا بنفسه"
        OTHER = "other", "أخرى"

    class CurrentSolution(models.TextChoices):
        NOTHING = "nothing", "لا شيء / دفتر"
        EXCEL = "excel", "إكسل"
        WHATSAPP = "whatsapp", "واتساب"
        COMPETITOR = "competitor", "برنامج منافس"
        OTHER = "other", "أخرى"

    class Language(models.TextChoices):
        ARABIC = "ar", "عربي"
        HEBREW = "he", "عبري"
        OTHER = "other", "أخرى"

    business_name = models.CharField("اسم المصلحة", max_length=200, blank=True)
    contact_name = models.CharField("اسم الشخص", max_length=150, blank=True)
    phone = models.CharField("الهاتف", max_length=30)
    phone_normalized = models.CharField(max_length=20, db_index=True, editable=False)
    phone_alt = models.CharField("هاتف إضافي", max_length=30, blank=True)
    phone_alt_normalized = models.CharField(max_length=20, blank=True, db_index=True, editable=False)
    email = models.EmailField("البريد الإلكتروني", blank=True)
    city = models.CharField("المدينة", max_length=100, blank=True, db_index=True)
    address = models.CharField("العنوان", max_length=255, blank=True)
    sector = models.ForeignKey(Sector, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="نوع المصلحة")
    employees_count = models.PositiveIntegerField("عدد الموظفين", null=True, blank=True)
    branches_count = models.PositiveIntegerField("عدد الفروع", null=True, blank=True)
    source = models.CharField("مصدر العميل", max_length=20, choices=Source.choices, default=Source.OTHER)
    language = models.CharField("لغة التواصل", max_length=10, choices=Language.choices, default=Language.ARABIC)
    current_solution = models.CharField("ماذا يستخدم حالياً؟", max_length=20, choices=CurrentSolution.choices, blank=True)
    competitor_name = models.CharField("اسم البرنامج المنافس", max_length=120, blank=True)
    contract_end_date = models.DateField("متى ينتهي عقده الحالي؟", null=True, blank=True)
    decision_maker_name = models.CharField("صاحب القرار", max_length=150, blank=True)
    decision_maker_phone = models.CharField("هاتف صاحب القرار", max_length=30, blank=True)
    quiet_hours = models.CharField("الوقت الهادئ عنده", max_length=100, blank=True, help_text="مثلاً: بين 3 و5 عصراً")
    tags = models.CharField("وسوم", max_length=255, blank=True, help_text="افصل بين الوسوم بفاصلة")
    notes = models.TextField("ملاحظات", blank=True)

    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="customers",
        verbose_name="التطبيق المستهدف",
    )
    stage = models.CharField("المرحلة", max_length=20, choices=Stage.choices, default=Stage.NEW, db_index=True)
    stage_changed_at = models.DateTimeField(default=timezone.now)
    lost_reason = models.ForeignKey(Reason, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="سبب الرفض")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="customers",
        verbose_name="الموظف المسؤول",
    )

    next_call_at = models.DateTimeField("الاتصال القادم", null=True, blank=True, db_index=True)
    last_call_at = models.DateTimeField("آخر اتصال", null=True, blank=True)
    last_outcome = models.CharField(max_length=20, blank=True)
    unanswered_attempts = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField("تاريخ الإضافة", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "عميل"
        verbose_name_plural = "العملاء"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        self.phone_normalized = phones.normalize(self.phone)
        self.phone_alt_normalized = phones.normalize(self.phone_alt)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("customer_detail", args=[self.pk])

    @property
    def display_name(self):
        return self.business_name or self.contact_name or self.phone

    @property
    def greeting_name(self):
        return self.contact_name or self.business_name

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.replace("،", ",").split(",") if t.strip()]

    @property
    def is_overdue(self):
        return bool(self.next_call_at and self.next_call_at < timezone.now())

    @property
    def last_outcome_label(self):
        return Call.Outcome(self.last_outcome).label if self.last_outcome in Call.Outcome.values else ""


class Call(models.Model):
    class Outcome(models.TextChoices):
        NO_ANSWER = "no_answer", "لم يرد"
        BUSY = "busy", "الخط مشغول"
        WRONG_NUMBER = "wrong_number", "رقم خطأ"
        CALLBACK = "callback", "اتصل لاحقاً"
        INFO_REQUESTED = "info_requested", "طلب تفاصيل / سأفكر"
        INTERESTED = "interested", "مهتم"
        DEMO_BOOKED = "demo_booked", "حُجز موعد عرض"
        NOT_INTERESTED = "not_interested", "غير مهتم"
        SOLD = "sold", "تم البيع"

    UNANSWERED = {"no_answer", "busy", "wrong_number"}

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="calls", verbose_name="العميل")
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="calls", verbose_name="الموظف")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="calls", verbose_name="التطبيق")
    outcome = models.CharField("النتيجة", max_length=20, choices=Outcome.choices, db_index=True)
    rejection_reason = models.ForeignKey(Reason, on_delete=models.SET_NULL, null=True, blank=True, related_name="calls", verbose_name="سبب الرفض")
    rejection_detail = models.CharField("تفاصيل السبب", max_length=255, blank=True)
    notes = models.TextField("ملاحظات المكالمة", blank=True)
    follow_up_at = models.DateTimeField("موعد المتابعة", null=True, blank=True)
    created_at = models.DateTimeField("وقت المكالمة", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "مكالمة"
        verbose_name_plural = "المكالمات"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.customer} - {self.get_outcome_display()}"

    @property
    def answered(self):
        return self.outcome not in self.UNANSWERED


class Appointment(models.Model):
    class Status(models.TextChoices):
        BOOKED = "booked", "محجوز"
        CONFIRMED = "confirmed", "مؤكَّد"
        ATTENDED = "attended", "حضر"
        NO_SHOW = "no_show", "لم يحضر"
        RESCHEDULED = "rescheduled", "تأجّل"
        CANCELLED = "cancelled", "ألغي"

    OPEN_STATUSES = {"booked", "confirmed"}

    class MeetingType(models.TextChoices):
        VISIT = "visit", "زيارة في مكان عمله"
        VIDEO = "video", "مكالمة فيديو"
        PHONE = "phone", "مكالمة هاتفية"
        OFFICE = "office", "في مكتبنا"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="appointments", verbose_name="العميل")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="التطبيق")
    scheduled_at = models.DateTimeField("الموعد", db_index=True)
    meeting_type = models.CharField("نوع الموعد", max_length=10, choices=MeetingType.choices, default=MeetingType.VISIT)
    location = models.CharField("العنوان أو رابط الاجتماع", max_length=255, blank=True)
    attendees = models.CharField("من سيحضر من طرف العميل؟", max_length=255, blank=True, help_text="شريك، مدير...")
    presenter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="presenting",
        verbose_name="من يقدّم العرض",
    )
    notes = models.TextField("ملاحظات", blank=True)
    status = models.CharField("الحالة", max_length=20, choices=Status.choices, default=Status.BOOKED, db_index=True)
    outcome_notes = models.TextField("ماذا حصل في الموعد؟", blank=True)
    booked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    rescheduled_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="rescheduled_to")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_whatsapp_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "موعد"
        verbose_name_plural = "المواعيد"
        ordering = ["scheduled_at"]

    def __str__(self):
        return f"{self.customer} - {timezone.localtime(self.scheduled_at):%d/%m %H:%M}"

    def get_absolute_url(self):
        return reverse("appointment_detail", args=[self.pk])

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_past(self):
        return self.scheduled_at < timezone.now()

    @property
    def needs_result(self):
        """موعد مضى وقته ولم تُسجل نتيجته."""
        return self.is_open and self.scheduled_at < timezone.now() - timedelta(minutes=30)

    @property
    def lead_days(self):
        """كم يوماً بين حجز الموعد وموعده."""
        return (timezone.localdate(self.scheduled_at) - timezone.localdate(self.created_at)).days


class Subscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "فعّال"
        PAUSED = "paused", "متوقف مؤقتاً"
        CANCELLED = "cancelled", "ملغى"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="subscriptions", verbose_name="العميل")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="subscriptions", verbose_name="التطبيق")
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="الباقة")
    monthly_price = models.DecimalField("السعر الشهري (₪)", max_digits=9, decimal_places=2)
    start_date = models.DateField("تاريخ البداية", default=timezone.localdate)
    status = models.CharField("الحالة", max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    cancelled_at = models.DateField("تاريخ الإلغاء", null=True, blank=True)
    cancel_reason = models.ForeignKey(Reason, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="سبب الإلغاء")
    cancel_notes = models.CharField("تفاصيل الإلغاء", max_length=255, blank=True)
    notes = models.TextField("ملاحظات", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "اشتراك"
        verbose_name_plural = "الاشتراكات"
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return f"{self.customer} - {self.product}"


class Activity(models.Model):
    class Kind(models.TextChoices):
        CALL = "call", "مكالمة"
        NOTE = "note", "ملاحظة"
        STAGE = "stage", "تغيير مرحلة"
        APPOINTMENT = "appointment", "موعد"
        WHATSAPP = "whatsapp", "واتساب"
        SUBSCRIPTION = "subscription", "اشتراك"
        SYSTEM = "system", "النظام"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="activities")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    text = models.TextField()
    call = models.ForeignKey(Call, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "نشاط"
        verbose_name_plural = "سجل النشاطات"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.text[:60]
