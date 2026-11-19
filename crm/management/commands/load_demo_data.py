"""بيانات تجريبية لتجربة النظام. لا تشغّله على النظام الحقيقي!

    python manage.py load_demo_data --yes
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from crm import services
from crm.models import Activity, Appointment, Customer, Plan, Product, Reason, Sector, Subscription, User

BUSINESSES = [
    ("صالون ليالي", "رنا عودة", "صالون / حلاقة / تجميل", "الناصرة"),
    ("حلاقة أبو أحمد", "أحمد خليل", "صالون / حلاقة / تجميل", "أم الفحم"),
    ("صالون روز", "نادين سليمان", "صالون / حلاقة / تجميل", "حيفا"),
    ("بيوتي لاونج", "هبة زعبي", "صالون / حلاقة / تجميل", "الطيبة"),
    ("صالون الأميرة", "سهى ناصر", "صالون / حلاقة / تجميل", "شفاعمرو"),
    ("ستايل للرجال", "إياد شلبي", "صالون / حلاقة / تجميل", "سخنين"),
    ("صالون لمسة", "لينا خوري", "صالون / حلاقة / تجميل", "عكا"),
    ("مطعم الزيتونة", "سامر حداد", "مطعم / مقهى", "الناصرة"),
    ("مقهى السرايا", "خالد مصاروة", "مطعم / مقهى", "الطيبة"),
    ("فلافل أبو شادي", "شادي عثامنة", "مطعم / مقهى", "الطيرة"),
    ("شاورما الأصيل", "محمد جبارين", "مطعم / مقهى", "أم الفحم"),
    ("مطعم البيت", "يوسف أبو حسين", "مطعم / مقهى", "يافا"),
    ("حلويات النابلسي", "ماجد قاسم", "مطعم / مقهى", "باقة الغربية"),
    ("بيتزا روما", "عمر دراوشة", "مطعم / مقهى", "كفر كنا"),
    ("عيادة د. سمير للأسنان", "د. سمير بشارة", "عيادة / طبي", "حيفا"),
    ("عيادة النور", "د. منى غنايم", "عيادة / طبي", "سخنين"),
    ("مركز العلاج الطبيعي", "رامي حسن", "عيادة / طبي", "الناصرة"),
    ("عيادة الشفاء", "د. وائل كيوان", "عيادة / طبي", "طمرة"),
    ("بصريات الرؤية", "سناء عزام", "عيادة / طبي", "عرابة"),
    ("سوبرماركت الأمانة", "جمال أبو ريا", "محل تجاري / بقالة", "رهط"),
    ("ملحمة الخليل", "طارق خليل", "محل تجاري / بقالة", "اللد"),
    ("مخبز الشام", "فادي حمدان", "محل تجاري / بقالة", "الرملة"),
    ("ميني ماركت السلام", "بلال مرعي", "محل تجاري / بقالة", "جلجولية"),
    ("بوتيك ريم", "ريم صالح", "ملابس وأحذية", "الناصرة"),
    ("أحذية الهدى", "هدى شحادة", "ملابس وأحذية", "طمرة"),
    ("أزياء العروس", "منال زبيدات", "ملابس وأحذية", "سخنين"),
    ("كراج الإخوة", "نزار عيسى", "ورشة / كراج", "شفاعمرو"),
    ("كراج أبو العبد", "عبد الله كناعنة", "ورشة / كراج", "عرابة"),
    ("مغسلة النجمة", "سليم بدارنة", "ورشة / كراج", "الطيرة"),
    ("نادي الأبطال", "علاء جبالي", "لياقة / جيم", "الطيبة"),
    ("فتنس زون", "كريم عباسي", "لياقة / جيم", "حيفا"),
    ("مركز الأوائل للدروس", "أ. نسرين زيدان", "تعليم / دورات", "كفر قاسم"),
    ("أكاديمية المستقبل", "أ. وسيم طه", "تعليم / دورات", "قلنسوة"),
    ("روضة البراعم", "دعاء مصالحة", "تعليم / دورات", "دبورية"),
    ("مكتب المحاسب ناصر", "ناصر حجازي", "مكتب / خدمات مهنية", "الناصرة"),
    ("مكتب تأمينات الأمل", "سامي خطيب", "مكتب / خدمات مهنية", "عكا"),
    ("مكتب عقارات الدار", "هاني سعدي", "عقارات", "يافا"),
    ("نزل الجليل", "جورج شحادة", "فندق / سياحة", "الناصرة"),
    ("صالون نور", "نور الهدى", "صالون / حلاقة / تجميل", "قلنسوة"),
    ("مطعم الريف", "حسن زيود", "مطعم / مقهى", "عين ماهل"),
    ("كافيه موكا", "مايا حداد", "مطعم / مقهى", "حيفا"),
    ("عيادة الأسرة", "د. ربيع حجاج", "عيادة / طبي", "رهط"),
    ("صيدلية الحياة", "سلمى أبو شقرة", "عيادة / طبي", "أم الفحم"),
    ("محمص البن الذهبي", "زياد عرموش", "محل تجاري / بقالة", "باقة الغربية"),
    ("ورشة الألمنيوم الحديثة", "مهدي ياسين", "ورشة / كراج", "كفر كنا"),
    ("استوديو لحظة", "تامر عواد", "مكتب / خدمات مهنية", "شفاعمرو"),
    ("صالون أناقة", "عبير قعدان", "صالون / حلاقة / تجميل", "باقة الغربية"),
    ("مطعم الشرق", "وليد طربيه", "مطعم / مقهى", "سخنين"),
    ("مركز تجميل لمار", "لمار حسون", "صالون / حلاقة / تجميل", "حيفا"),
    ("حضانة الفراشة", "رهام عبد الحليم", "تعليم / دورات", "الطيبة"),
    ("مكتبة الرسالة", "أنس نصار", "محل تجاري / بقالة", "عرابة"),
    ("بوتيك لارا", "لارا منصور", "ملابس وأحذية", "حيفا"),
    ("كراج السرعة", "مؤمن قبلاوي", "ورشة / كراج", "أم الفحم"),
    ("جيم القمة", "رائد شلاعطة", "لياقة / جيم", "سخنين"),
    ("عيادة ابتسامة", "د. هالة جبارة", "عيادة / طبي", "الطيبة"),
]

PRODUCTS = [
    ("تطبيق المواعيد", "حجز مواعيد أونلاين للزبائن مع تذكير تلقائي بالواتساب، وإدارة جدول العمال.",
     "صالونات، عيادات، مراكز تجميل", Decimal("350"), [("أساسي", "350"), ("متقدم", "600")]),
    ("نظام الكاشير والمخزون", "نقطة بيع مع فواتير، إدارة مخزون، وتقارير مبيعات يومية.",
     "مطاعم، مقاهي، محلات", Decimal("650"), [("فرع واحد", "650"), ("عدة فروع", "1200")]),
    ("تطبيق ولاء الزبائن", "نقاط ومكافآت للزبائن الدائمين وحملات واتساب.",
     "مطاعم، صالونات، محلات", Decimal("300"), []),
    ("نظام إدارة العيادة", "ملفات مرضى، مواعيد، وفواتير في مكان واحد.",
     "عيادات ومراكز طبية", Decimal("1500"), []),
]

PRODUCT_FOR_SECTOR = {
    "صالون / حلاقة / تجميل": 0, "عيادة / طبي": 3, "مطعم / مقهى": 1, "محل تجاري / بقالة": 1,
    "ملابس وأحذية": 1, "لياقة / جيم": 0, "تعليم / دورات": 0,
}

OUTCOME_WEIGHTS = [
    ("no_answer", 30), ("busy", 5), ("callback", 10), ("info_requested", 8), ("interested", 9),
    ("demo_booked", 13), ("not_interested", 20), ("sold", 4), ("wrong_number", 1),
]
REASON_WEIGHTS = {
    "السعر غالي": 9, "لا يحتاج / مرتاح بالوضع الحالي": 8, "عنده برنامج آخر": 6, "التوقيت غير مناسب": 5,
    "لا وقت للتعلم / يخاف من التعقيد": 4, "«سأفكر» / رفض مهذب": 3, "ليس صاحب القرار": 3,
    "ميزة ناقصة": 3, "لا يثق بشركة جديدة": 2, "أغلق الخط فوراً": 2,
}
MISSING_FEATURES = ["ربط مع برنامج الحسابات", "تطبيق بالعبري", "دفع ببطاقة الائتمان", "تقارير للمحاسب", "تذكير SMS"]
COMPETITORS = ["Tor4You", "Priority", "برنامج محلي", "Shopify POS"]


class Command(BaseCommand):
    help = "تعبئة النظام ببيانات تجريبية (للتجربة فقط)"

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="تأكيد إضافة بيانات تجريبية")
        parser.add_argument("--password", default="demo12345", help="كلمة مرور الحسابات التجريبية")
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError("هذا الأمر يضيف بيانات وهمية. أضف --yes للتأكيد. لا تشغّله على النظام الحقيقي.")
        if Customer.objects.exists():
            raise CommandError("يوجد عملاء في النظام مسبقاً — لن نضيف بيانات تجريبية فوقهم.")
        rng = random.Random(options["seed"])
        with transaction.atomic():
            manager, agent = self.make_users(options["password"])
            products = self.make_products()
            self.make_customers(rng, manager, agent, products)
        self.stdout.write(self.style.SUCCESS(
            f"تمت إضافة البيانات التجريبية. الدخول: manager أو agent — كلمة المرور: {options['password']}"
        ))

    def make_users(self, password):
        manager, _ = User.objects.get_or_create(
            username="manager", defaults={"first_name": "المدير", "role": User.Role.ADMIN, "is_staff": True}
        )
        agent, _ = User.objects.get_or_create(
            username="agent", defaults={"first_name": "سامي", "last_name": "(موظف الاتصال)", "role": User.Role.AGENT}
        )
        for user in (manager, agent):
            user.set_password(password)
            user.save()
        return manager, agent

    def make_products(self):
        products = []
        for order, (name, description, target, price, plans) in enumerate(PRODUCTS):
            product, _ = Product.objects.get_or_create(name=name, defaults={
                "description": description, "target_customers": target, "monthly_price": price, "order": order,
                "call_script": (
                    f"١. الافتتاحية: «مرحبا، معك سامي من TBT. بعرف إنك مشغول، بتعطيني 30 ثانية؟ "
                    f"بنساعد {target} يوفّروا وقت ويزيدوا الزبائن مع {name}.»\n\n"
                    "٢. أسئلة: كيف بتنظّم الشغل هلأ؟ كم مرة بيصير إنه زبون بيضيع؟ مين صاحب القرار؟\n\n"
                    f"٣. الفائدة: {description}\n\n"
                    "٤. الخطوة التالية: «خلينا نعمل 15 دقيقة عندك بالمحل. إيمتى الوقت الهادي عندك؟»"
                ),
            })
            for plan_order, (plan_name, plan_price) in enumerate(plans):
                Plan.objects.get_or_create(product=product, name=plan_name,
                                           defaults={"monthly_price": Decimal(plan_price), "order": plan_order})
            products.append(product)
        return products

    def make_customers(self, rng, manager, agent, products):
        now = timezone.now()
        sectors = {s.name: s for s in Sector.objects.all()}
        reasons = {r.text: r for r in Reason.objects.filter(kind=Reason.Kind.REJECTION)}
        cancel_reasons = list(Reason.objects.filter(kind=Reason.Kind.CANCELLATION))
        outcomes, weights = zip(*OUTCOME_WEIGHTS)
        reason_names, reason_weights = zip(*REASON_WEIGHTS.items())

        for index, (business, contact, sector_name, city) in enumerate(BUSINESSES):
            product = products[PRODUCT_FOR_SECTOR.get(sector_name, 2)]
            created = now - timedelta(days=rng.randint(26, 40), hours=rng.randint(0, 8))
            customer = Customer.objects.create(
                business_name=business, contact_name=contact, phone=f"050000{index:04d}",
                city=city, sector=sectors.get(sector_name), product=product, assigned_to=agent,
                source=rng.choice([Customer.Source.IMPORTED] * 4 + [Customer.Source.REFERRAL, Customer.Source.AD]),
                employees_count=rng.choice([None, 2, 3, 5, 8, 12]), created_by=manager,
                quiet_hours=rng.choice(["", "", "بين 3 و5 عصراً", "الصباح الباكر", "بعد الساعة 2"]),
                created_at=created, stage_changed_at=created,
            )
            Activity.objects.create(customer=customer, user=manager, kind=Activity.Kind.SYSTEM,
                                    text="أُضيف من ملف: قائمة العملاء.xlsx", created_at=created)
            if index % 5 == 4:  # عملاء جدد لم نتصل بهم بعد
                continue

            moment = created + timedelta(days=rng.randint(1, 4), hours=rng.randint(1, 6))
            for _attempt in range(rng.randint(1, 4)):
                if moment > now - timedelta(hours=1):
                    break
                outcome = rng.choices(outcomes, weights)[0]
                moment = self.log(rng, customer, agent, outcome, moment, product, reasons, reason_names, reason_weights, now)
                if outcome in ("sold", "not_interested", "wrong_number", "demo_booked"):
                    break

        self.tidy_followups(rng, now)
        self.finish_appointments(rng, agent, products, cancel_reasons, now)
        self.upcoming(agent, now, cancel_reasons)

    def upcoming(self, agent, now, cancel_reasons):
        """مواعيد قادمة (اليوم وغداً) واشتراك ملغى، حتى تظهر كل الشاشات بشكل كامل."""
        candidates = Customer.objects.filter(stage__in=["contacted", "interested", "new"], last_call_at__isnull=False)
        slots = [(0, 17), (1, 10), (1, 15), (2, 12)]
        for customer, (days, hour) in zip(candidates.order_by("pk")[:4], slots):
            when = services.local_dt(timezone.localdate() + timedelta(days=days), hour)
            if when <= now:
                when = now + timedelta(hours=2)
            services.book_appointment(customer, agent, {
                "scheduled_at": when, "meeting_type": Appointment.MeetingType.VISIT, "presenter": agent,
                "product": customer.product, "location": customer.city,
            })
            customer.refresh_from_db()
            customer.next_call_at = None
            customer.save(update_fields=["next_call_at"])
        subscription = Subscription.objects.filter(status=Subscription.Status.ACTIVE).order_by("pk").first()
        if subscription and cancel_reasons:
            subscription.status = Subscription.Status.CANCELLED
            subscription.cancel_reason = cancel_reasons[0]
            subscription.cancelled_at = timezone.localdate() - timedelta(days=3)
            subscription.save()

    def log(self, rng, customer, agent, outcome, moment, product, reasons, reason_names, reason_weights, now):
        local_moment = timezone.localtime(moment).replace(hour=rng.choice([9, 10, 11, 13, 14, 16, 17]), minute=rng.choice([0, 10, 25, 40]))
        moment = min(local_moment, now - timedelta(minutes=30))
        kwargs = {"customer": customer, "user": agent, "outcome": outcome, "product": product, "now": moment}
        if outcome in ("callback", "info_requested", "interested"):
            kwargs["follow_up_at"] = moment + timedelta(days=rng.randint(1, 3))
            kwargs["notes"] = rng.choice(["طلب أن نتصل بعد الظهر", "مهتم لكن مشغول هذا الأسبوع", "بدّه يشوف الأسعار", ""])
        if outcome == "not_interested":
            reason = reasons[rng.choices(reason_names, reason_weights)[0]]
            kwargs["rejection_reason"] = reason
            if reason.requires_detail:
                kwargs["rejection_detail"] = rng.choice(MISSING_FEATURES)
            if reason.asks_contract_end:
                kwargs["rejection_detail"] = rng.choice(COMPETITORS)
                kwargs["contract_end_date"] = timezone.localdate() + timedelta(days=rng.randint(20, 110))
        if outcome == "demo_booked":
            lead = rng.choice([0, 1, 1, 2, 3, 5, 7])
            when = timezone.localtime(moment + timedelta(days=lead)).replace(hour=rng.choice([10, 12, 15]), minute=0)
            if when <= moment:
                when += timedelta(days=1)
            kwargs["appointment_data"] = {
                "scheduled_at": when, "meeting_type": rng.choice(["visit", "visit", "video", "phone"]),
                "presenter": agent, "location": customer.city,
            }
        if outcome == "sold":
            kwargs["subscription_data"] = {"product": product, "monthly_price": product.monthly_price,
                                           "start_date": timezone.localdate(moment)}
        marker = timezone.now()
        _call, appointment, subscription, _info = services.log_call(**kwargs)
        Activity.objects.filter(customer=customer, created_at__gte=marker).update(created_at=moment)
        Customer.objects.filter(pk=customer.pk, stage_changed_at__gte=marker).update(stage_changed_at=moment)
        if appointment:
            Appointment.objects.filter(pk=appointment.pk).update(created_at=moment)
        if subscription:
            Subscription.objects.filter(pk=subscription.pk).update(created_at=moment)
        customer.refresh_from_db()
        return moment + timedelta(days=rng.randint(1, 4), hours=rng.randint(0, 5))

    def tidy_followups(self, rng, now):
        """توزيع المتابعات: بعضها مستحق الآن وبعضها لاحقاً اليوم والباقي في الأيام القادمة."""
        overdue = list(Customer.objects.filter(next_call_at__lt=now).order_by("pk"))
        for position, customer in enumerate(overdue):
            if position < 7:
                customer.next_call_at = now - timedelta(minutes=rng.randint(10, 300))
            elif position < 10:
                customer.next_call_at = min(now + timedelta(hours=rng.randint(1, 4)), services.end_of_today())
            else:
                day = timezone.localdate() + timedelta(days=rng.randint(1, 6))
                customer.next_call_at = services.local_dt(day, rng.choice([10, 12, 15, 17]))
            customer.save(update_fields=["next_call_at"])

    def finish_appointments(self, rng, agent, products, cancel_reasons, now):
        for appointment in Appointment.objects.select_related("customer").order_by("pk"):
            customer = appointment.customer
            if appointment.scheduled_at > now:
                if rng.random() < 0.4:
                    services.confirm_appointment(appointment, agent)
                continue
            # المواعيد البعيدة عن الحجز يغيب عنها الناس أكثر
            no_show_chance = 0.15 + 0.07 * max(appointment.lead_days, 0)
            if rng.random() < no_show_chance:
                appointment.status = Appointment.Status.NO_SHOW
                appointment.save(update_fields=["status"])
                Activity.objects.create(customer=customer, user=agent, kind=Activity.Kind.APPOINTMENT,
                                        text="لم يحضر الموعد", appointment=appointment, created_at=appointment.scheduled_at)
                customer.next_call_at = now - timedelta(minutes=rng.randint(5, 90))
                customer.save(update_fields=["next_call_at"])
                continue
            if appointment.lead_days <= 1 and rng.random() < 0.6:
                appointment.confirmed_at = appointment.created_at
            appointment.status = Appointment.Status.ATTENDED
            appointment.outcome_notes = rng.choice(["أعجبه التطبيق وطلب عرض سعر", "يريد أن يفكر مع شريكه", "اشترك في نفس اللقاء"])
            appointment.save(update_fields=["status", "outcome_notes", "confirmed_at"])
            if rng.random() < 0.55:
                product = appointment.product or products[0]
                start = timezone.localdate(appointment.scheduled_at)
                subscription = Subscription.objects.create(
                    customer=customer, product=product, monthly_price=product.monthly_price, start_date=start, created_by=agent,
                )
                services.change_stage(customer, Customer.Stage.WON, agent)
                customer.next_call_at = None
                customer.save(update_fields=["next_call_at"])
                if rng.random() < 0.15 and cancel_reasons:
                    subscription.status = Subscription.Status.CANCELLED
                    subscription.cancel_reason = rng.choice(cancel_reasons)
                    subscription.cancelled_at = min(start + timedelta(days=rng.randint(5, 20)), timezone.localdate())
                    subscription.save()
            else:
                services.change_stage(customer, Customer.Stage.OFFER, agent)
                customer.next_call_at = now + timedelta(days=rng.randint(1, 3))
                customer.save(update_fields=["next_call_at"])
