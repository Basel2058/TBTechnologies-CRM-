import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crm.models import Activity, Appointment, Call, Customer, MessageTemplate, Product, Reason, Subscription, User


def dt_input(value):
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")


class ViewTestCase(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user("boss", password="pass12345!", role=User.Role.ADMIN)
        self.agent = User.objects.create_user("agent", password="pass12345!", role=User.Role.AGENT, first_name="سامي")
        self.other_agent = User.objects.create_user("agent2", password="pass12345!", role=User.Role.AGENT)
        self.product = Product.objects.create(name="تطبيق المواعيد", monthly_price=Decimal("350"))
        self.mine = Customer.objects.create(business_name="صالون ليالي", phone="0501112233", assigned_to=self.agent, product=self.product)
        self.theirs = Customer.objects.create(business_name="مطعم الزيتونة", phone="0502223344", assigned_to=self.other_agent)

    def login(self, user):
        self.client.force_login(user)


class AccessTests(ViewTestCase):
    def test_login_required(self):
        response = self.client.get(reverse("customer_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_agent_sees_only_own_customers(self):
        self.login(self.agent)
        response = self.client.get(reverse("customer_list"))
        self.assertContains(response, "صالون ليالي")
        self.assertNotContains(response, "مطعم الزيتونة")
        self.assertEqual(self.client.get(reverse("customer_detail", args=[self.theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("call", args=[self.theirs.pk])).status_code, 404)

    def test_agent_cannot_export_delete_or_see_reports(self):
        self.login(self.agent)
        for name, args in [("customer_export", []), ("customer_delete", [self.mine.pk]), ("reports", []),
                           ("settings", []), ("import_upload", []), ("backup_download", [])]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)

    def test_manager_sees_everything(self):
        self.login(self.manager)
        response = self.client.get(reverse("customer_list"))
        self.assertContains(response, "صالون ليالي")
        self.assertContains(response, "مطعم الزيتونة")
        for name in ["dashboard", "queue", "pipeline", "appointment_list", "opportunities", "product_list",
                     "subscription_list", "reports", "settings", "user_list", "import_upload", "settings_backup"]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_export_returns_excel(self):
        self.login(self.manager)
        response = self.client.get(reverse("customer_export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])

    def test_backup_download(self):
        self.login(self.manager)
        response = self.client.get(reverse("backup_download"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"SQLite format 3"))


class CustomerFormTests(ViewTestCase):
    def test_agent_creates_customer_assigned_to_self(self):
        self.login(self.agent)
        response = self.client.post(reverse("customer_new"), {
            "business_name": "كراج الإخوة", "phone": "+972 54 765 4321", "source": "other", "language": "ar",
        })
        customer = Customer.objects.get(business_name="كراج الإخوة")
        self.assertRedirects(response, customer.get_absolute_url())
        self.assertEqual(customer.assigned_to, self.agent)
        self.assertEqual(customer.phone_normalized, "0547654321")

    def test_duplicate_phone_is_rejected_in_any_format(self):
        self.login(self.agent)
        response = self.client.post(reverse("customer_new"), {
            "business_name": "نسخة", "phone": "972-50-111-2233", "source": "other", "language": "ar",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "هذا الرقم مسجّل للعميل")
        self.assertContains(response, f'href="{self.mine.get_absolute_url()}"')

    def test_name_required(self):
        self.login(self.agent)
        response = self.client.post(reverse("customer_new"), {"phone": "0509998877", "source": "other", "language": "ar"})
        self.assertContains(response, "اكتب اسم المصلحة أو اسم الشخص")


class CallFlowTests(ViewTestCase):
    def call_url(self, customer, queue=False):
        return reverse("call", args=[customer.pk]) + ("?mode=queue" if queue else "")

    def test_callback_requires_follow_up(self):
        self.login(self.agent)
        response = self.client.post(self.call_url(self.mine), {"outcome": "callback"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Call.objects.count(), 0)
        self.assertContains(response, "حدّد يوماً وساعة")

    def test_not_interested_requires_reason(self):
        self.login(self.agent)
        response = self.client.post(self.call_url(self.mine), {"outcome": "not_interested"})
        self.assertEqual(Call.objects.count(), 0)
        self.assertContains(response, "اختر سبب الرفض")
        reason = Reason.objects.get(kind="rejection", text="ميزة ناقصة")
        response = self.client.post(self.call_url(self.mine), {"outcome": "not_interested", "rejection_reason": reason.pk})
        self.assertContains(response, "اكتب التفاصيل")

    def test_log_call_and_continue_in_queue(self):
        self.login(self.agent)
        second = Customer.objects.create(business_name="بيتزا روما", phone="0503334455", assigned_to=self.agent)
        response = self.client.post(self.call_url(self.mine, queue=True), {
            "outcome": "callback", "follow_up_at": dt_input(timezone.now() + timedelta(days=1)), "mode": "queue",
        })
        self.assertRedirects(response, reverse("queue_next"), fetch_redirect_response=False)
        response = self.client.get(reverse("queue_next"))
        self.assertRedirects(response, self.call_url(second, queue=True), fetch_redirect_response=False)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.stage, Customer.Stage.CONTACTED)

    def test_skip_in_queue(self):
        self.login(self.agent)
        Customer.objects.create(business_name="بيتزا روما", phone="0503334455", assigned_to=self.agent)
        first = self.client.get(reverse("queue_next") + "?reset=1")["Location"]
        self.assertIn(str(self.mine.pk), first)
        nxt = self.client.get(reverse("queue_next") + f"?skip={self.mine.pk}")["Location"]
        self.assertNotIn(f"/customers/{self.mine.pk}/", nxt)

    def test_demo_booking_sets_whatsapp_prompt(self):
        self.login(self.agent)
        self.client.post(self.call_url(self.mine), {
            "outcome": "demo_booked", "appt_at": dt_input(timezone.now() + timedelta(days=1)), "appt_type": "visit",
        })
        appointment = Appointment.objects.get()
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "wa-banner")
        self.assertContains(response, reverse("appointment_whatsapp", args=[appointment.pk, MessageTemplate.objects.filter(context="appointment").first().pk]))
        # تظهر مرة واحدة فقط
        self.assertNotContains(self.client.get(reverse("dashboard")), "wa-banner")

    def test_sold_uses_product_price_when_empty(self):
        self.login(self.agent)
        self.client.post(self.call_url(self.mine), {"outcome": "sold", "product": self.product.pk})
        subscription = Subscription.objects.get()
        self.assertEqual(subscription.monthly_price, Decimal("350"))

    def test_whatsapp_redirect_logs_activity(self):
        self.login(self.agent)
        template = MessageTemplate.objects.filter(context="customer").first()
        response = self.client.post(reverse("customer_whatsapp", args=[self.mine.pk, template.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("https://wa.me/972501112233?text="))
        self.assertTrue(Activity.objects.filter(customer=self.mine, kind=Activity.Kind.WHATSAPP).exists())


class StageAndAppointmentViewTests(ViewTestCase):
    def test_kanban_json_stage_change(self):
        self.login(self.agent)
        reason = Reason.objects.get(kind="rejection", text="السعر غالي")
        response = self.client.post(
            reverse("customer_stage", args=[self.mine.pk]),
            data=json.dumps({"stage": "lost", "lost_reason": reason.pk}), content_type="application/json",
        )
        self.assertEqual(response.json()["label"], "غير مهتم")
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.lost_reason, reason)

    def test_won_without_subscription_asks_for_one(self):
        self.login(self.agent)
        response = self.client.post(
            reverse("customer_stage", args=[self.mine.pk]), data=json.dumps({"stage": "won"}), content_type="application/json",
        )
        self.assertEqual(response.json()["subscription_url"], reverse("subscription_new", args=[self.mine.pk]))

    def test_no_show_flow(self):
        self.login(self.agent)
        appointment = Appointment.objects.create(customer=self.mine, scheduled_at=timezone.now() - timedelta(hours=1))
        response = self.client.post(reverse("appointment_no_show", args=[appointment.pk]))
        self.assertRedirects(response, reverse("appointment_detail", args=[appointment.pk]))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.NO_SHOW)
        # لا يمكن تسجيل «حضر» لموعد أُغلق
        self.client.post(reverse("appointment_attended", args=[appointment.pk]), {"outcome_notes": "x"})
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.NO_SHOW)

    def test_attended_with_won_redirects_to_subscription(self):
        self.login(self.agent)
        appointment = Appointment.objects.create(customer=self.mine, scheduled_at=timezone.now() - timedelta(hours=1))
        response = self.client.post(reverse("appointment_attended", args=[appointment.pk]), {"outcome_notes": "ممتاز", "new_stage": "won"})
        self.assertRedirects(response, reverse("subscription_new", args=[self.mine.pk]))

    def test_cancel_subscription_records_reason(self):
        self.login(self.manager)
        subscription = Subscription.objects.create(customer=self.mine, product=self.product, monthly_price=350)
        reason = Reason.objects.filter(kind="cancellation", requires_detail=False).first()
        self.client.post(reverse("subscription_cancel", args=[subscription.pk]), {
            "cancel_reason": reason.pk, "cancelled_at": timezone.localdate().isoformat(),
        })
        subscription.refresh_from_db()
        self.mine.refresh_from_db()
        self.assertEqual(subscription.status, Subscription.Status.CANCELLED)
        self.assertEqual(self.mine.stage, Customer.Stage.LOST)


class SettingsTests(ViewTestCase):
    def test_manager_creates_agent(self):
        self.login(self.manager)
        response = self.client.post(reverse("user_new"), {
            "username": "ahmad", "first_name": "أحمد", "last_name": "", "role": "agent",
            "password1": "Strong-pass-2026", "password2": "Strong-pass-2026",
        })
        self.assertRedirects(response, reverse("user_list"))
        self.assertTrue(User.objects.get(username="ahmad").check_password("Strong-pass-2026"))

    def test_manager_cannot_demote_self(self):
        self.login(self.manager)
        self.client.post(reverse("user_edit", args=[self.manager.pk]), {"first_name": "x", "last_name": "", "role": "agent", "is_active": "on"})
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.role, User.Role.ADMIN)

    def test_product_with_plans(self):
        self.login(self.manager)
        response = self.client.post(reverse("product_new"), {
            "name": "نظام الكاشير", "monthly_price": "650", "order": "0", "call_script": "نص", "is_active": "on",
            "plans-TOTAL_FORMS": "2", "plans-INITIAL_FORMS": "0", "plans-MIN_NUM_FORMS": "0", "plans-MAX_NUM_FORMS": "1000",
            "plans-0-name": "فرع واحد", "plans-0-monthly_price": "650", "plans-0-order": "0",
            "plans-1-name": "", "plans-1-monthly_price": "", "plans-1-order": "0",
        })
        product = Product.objects.get(name="نظام الكاشير")
        self.assertRedirects(response, product.get_absolute_url())
        self.assertEqual(product.plans.get().monthly_price, Decimal("650"))

    def test_simple_crud_pages(self):
        self.login(self.manager)
        response = self.client.post(reverse("settings_reasons_new"), {"kind": "rejection", "text": "سبب جديد", "is_active": "on", "order": "50"})
        self.assertRedirects(response, reverse("settings_reasons"))
        self.assertTrue(Reason.objects.filter(text="سبب جديد").exists())
        self.assertContains(self.client.get(reverse("settings_templates_edit", args=[MessageTemplate.objects.first().pk])), "{الاسم}")


class DashboardTests(ViewTestCase):
    def test_team_counts_are_not_multiplied_by_customers(self):
        from crm import services

        Customer.objects.create(business_name="ثالث", phone="0505556677", assigned_to=self.agent)
        services.log_call(customer=self.mine, user=self.agent, outcome="no_answer")
        self.login(self.manager)
        team = {m.pk: m for m in self.client.get(reverse("dashboard")).context["team"]}
        self.assertEqual(team[self.agent.pk].calls_today, 1)
        self.assertEqual(team[self.agent.pk].customers_count, 2)
