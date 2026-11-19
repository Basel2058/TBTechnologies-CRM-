from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from crm import services
from crm.models import Activity, Appointment, Call, Customer, MessageTemplate, Product, Reason, Subscription, User


def local(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class BaseCase(TestCase):
    def setUp(self):
        self.agent = User.objects.create_user("agent", password="x", role=User.Role.AGENT, first_name="سامي")
        self.product = Product.objects.create(name="تطبيق المواعيد", monthly_price=Decimal("350"))
        self.customer = Customer.objects.create(
            business_name="صالون ليالي", contact_name="رنا", phone="0501112233", assigned_to=self.agent, product=self.product,
        )

    def log(self, outcome, **kwargs):
        return services.log_call(customer=self.customer, user=self.agent, outcome=outcome, **kwargs)


class RetryTests(BaseCase):
    def test_retry_time_alternates_time_of_day(self):
        today = date(2026, 11, 19)
        self.assertEqual(services.retry_time(local(today, 10), 1), local(today + timedelta(days=1), 15))
        self.assertEqual(services.retry_time(local(today, 16), 1), local(today + timedelta(days=1), 10))
        self.assertEqual(services.retry_time(local(today, 10), 2), local(today + timedelta(days=2), 15))
        self.assertEqual(services.retry_time(local(today, 10), 4), local(today + timedelta(days=3), 15))

    def test_busy_retries_later_same_day(self):
        today = date(2026, 11, 19)
        self.assertEqual(services.retry_time(local(today, 10), 1, busy=True), local(today, 12))
        self.assertEqual(services.retry_time(local(today, 18), 1, busy=True), local(today + timedelta(days=1), 10))

    def test_no_answer_schedules_retry_and_counts_attempts(self):
        self.log("no_answer")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.unanswered_attempts, 1)
        self.assertIsNotNone(self.customer.next_call_at)
        self.assertEqual(self.customer.stage, Customer.Stage.NEW)  # لم نتواصل معه فعلاً بعد

    def test_stops_after_max_attempts(self):
        with self.settings(TBT={**settings.TBT, "MAX_UNANSWERED_ATTEMPTS": 3}):
            for _ in range(2):
                self.log("no_answer")
            _call, _a, _s, info = self.log("no_answer")
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.next_call_at)
        self.assertEqual(self.customer.stage, Customer.Stage.LOST)
        self.assertTrue(info)

    def test_answer_resets_attempts(self):
        self.log("no_answer")
        self.log("callback", follow_up_at=timezone.now() + timedelta(days=1))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.unanswered_attempts, 0)
        self.assertEqual(self.customer.stage, Customer.Stage.CONTACTED)


class OutcomeTests(BaseCase):
    def test_follow_up_is_saved_as_next_call(self):
        when = timezone.now() + timedelta(days=2)
        self.log("interested", follow_up_at=when)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.next_call_at, when)
        self.assertEqual(self.customer.stage, Customer.Stage.INTERESTED)

    def test_not_interested_records_reason(self):
        reason = Reason.objects.get(kind="rejection", text="السعر غالي")
        self.log("not_interested", rejection_reason=reason)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.stage, Customer.Stage.LOST)
        self.assertEqual(self.customer.lost_reason, reason)
        self.assertIsNone(self.customer.next_call_at)
        self.assertEqual(Call.objects.get().rejection_reason, reason)

    def test_competitor_contract_schedules_call_a_month_before(self):
        reason = Reason.objects.get(asks_contract_end=True)
        end = timezone.localdate() + timedelta(days=90)
        _call, _a, _s, info = self.log("not_interested", rejection_reason=reason, rejection_detail="Tor4You", contract_end_date=end)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.competitor_name, "Tor4You")
        self.assertEqual(self.customer.contract_end_date, end)
        self.assertEqual(timezone.localtime(self.customer.next_call_at).date(), end - timedelta(days=30))
        self.assertTrue(info)

    def test_demo_booked_creates_appointment(self):
        when = timezone.now() + timedelta(days=1)
        _call, appointment, _s, _i = self.log("demo_booked", appointment_data={"scheduled_at": when, "meeting_type": "visit"})
        self.customer.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.BOOKED)
        self.assertEqual(appointment.product, self.product)
        self.assertEqual(self.customer.stage, Customer.Stage.DEMO)
        self.assertTrue(Activity.objects.filter(customer=self.customer, kind=Activity.Kind.APPOINTMENT).exists())

    def test_sold_creates_subscription(self):
        _call, _a, subscription, _i = self.log("sold", subscription_data={
            "product": self.product, "monthly_price": Decimal("350"), "start_date": timezone.localdate(),
        })
        self.customer.refresh_from_db()
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.customer.stage, Customer.Stage.WON)

    def test_stage_only_moves_forward(self):
        services.change_stage(self.customer, Customer.Stage.OFFER, self.agent)
        self.log("interested", follow_up_at=timezone.now() + timedelta(days=1))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.stage, Customer.Stage.OFFER)

    def test_lost_customer_can_come_back(self):
        services.change_stage(self.customer, Customer.Stage.LOST, self.agent)
        self.log("interested", follow_up_at=timezone.now() + timedelta(days=1))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.stage, Customer.Stage.INTERESTED)
        self.assertIsNone(self.customer.lost_reason)

    def test_subscriber_stays_won_when_upsell_is_rejected(self):
        Subscription.objects.create(customer=self.customer, product=self.product, monthly_price=350)
        services.change_stage(self.customer, Customer.Stage.WON, self.agent)
        other = Product.objects.create(name="الكاشير", monthly_price=650)
        self.log("not_interested", product=other, rejection_reason=Reason.objects.get(kind="rejection", text="السعر غالي"))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.stage, Customer.Stage.WON)

    def test_wrong_number_stops_calls(self):
        self.customer.next_call_at = timezone.now()
        self.customer.save()
        self.log("wrong_number")
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.next_call_at)
        self.assertEqual(self.customer.stage, Customer.Stage.LOST)


class AppointmentTests(BaseCase):
    def book(self, days=1):
        return services.book_appointment(self.customer, self.agent, {
            "scheduled_at": timezone.now() + timedelta(days=days), "meeting_type": "visit",
        })

    def test_first_no_show_puts_customer_at_top_of_queue(self):
        appointment = self.book()
        services.mark_no_show(appointment, self.agent)
        self.customer.refresh_from_db()
        self.assertLessEqual(self.customer.next_call_at, timezone.now())
        self.assertEqual(services.next_in_queue(Customer.objects.all()), self.customer)

    def test_second_no_show_moves_follow_up_a_month_later(self):
        services.mark_no_show(self.book(), self.agent)
        services.mark_no_show(self.book(2), self.agent)
        self.customer.refresh_from_db()
        self.assertGreater(self.customer.next_call_at, timezone.now() + timedelta(days=25))
        self.assertEqual(self.customer.stage, Customer.Stage.INTERESTED)

    def test_reschedule_after_no_show_keeps_the_statistic(self):
        appointment = self.book()
        services.mark_no_show(appointment, self.agent)
        new = services.reschedule_appointment(appointment, self.agent, {"scheduled_at": timezone.now() + timedelta(days=1)})
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.NO_SHOW)
        self.assertEqual(new.rescheduled_from, appointment)
        self.assertEqual(new.status, Appointment.Status.BOOKED)

    def test_reschedule_open_appointment(self):
        appointment = self.book()
        services.reschedule_appointment(appointment, self.agent, {"scheduled_at": timezone.now() + timedelta(days=3)})
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.RESCHEDULED)

    def test_buckets(self):
        soon = self.book(1)
        past = services.book_appointment(self.customer, self.agent, {
            "scheduled_at": timezone.now() - timedelta(hours=2), "meeting_type": "visit",
        })
        buckets = services.appointment_buckets(Appointment.objects.all())
        self.assertIn(soon, buckets["needs_confirmation"])
        self.assertIn(past, buckets["needs_result"])
        services.confirm_appointment(soon, self.agent)
        self.assertNotIn(soon, services.appointment_buckets(Appointment.objects.all())["needs_confirmation"])


class QueueTests(BaseCase):
    def test_queue_sections(self):
        new = self.customer
        due = Customer.objects.create(business_name="مستحق", phone="0502223344", next_call_at=timezone.now() - timedelta(hours=1))
        later = Customer.objects.create(business_name="لاحقاً", phone="0503334455", next_call_at=min(
            timezone.now() + timedelta(minutes=5), services.end_of_today()))
        future = Customer.objects.create(business_name="غداً", phone="0504445566", next_call_at=timezone.now() + timedelta(days=2))
        queue = services.call_queue(Customer.objects.all())
        self.assertEqual(list(queue["due"]), [due])
        self.assertIn(later, queue["later_today"])
        self.assertEqual(list(queue["new"]), [new])
        self.assertNotIn(future, list(queue["due"]) + list(queue["new"]))
        self.assertEqual(services.next_in_queue(Customer.objects.all()), due)
        self.assertEqual(services.next_in_queue(Customer.objects.all(), skip_ids=[due.pk]), new)


class MessageTests(BaseCase):
    def test_render_message_fills_placeholders(self):
        appointment = services.book_appointment(self.customer, self.agent, {
            "scheduled_at": local(date(2026, 11, 22), 15), "meeting_type": "visit", "product": self.product,
        })
        body = "أهلاً {الاسم}، معك {الموظف} من {الشركة}. موعدنا يوم {اليوم} {التاريخ} الساعة {الوقت} عن {التطبيق}. {مجهول}"
        text = services.render_message(body, self.customer, self.agent, appointment)
        self.assertEqual(text, "أهلاً رنا، معك سامي من TBT. موعدنا يوم الأحد 22/11 الساعة 15:00 عن تطبيق المواعيد. {مجهول}")

    def test_default_templates_exist(self):
        self.assertTrue(MessageTemplate.objects.filter(context="appointment").exists())
        self.assertTrue(Reason.objects.filter(kind="cancellation").exists())
