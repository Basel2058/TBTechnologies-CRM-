from django.test import SimpleTestCase

from crm import phones


class NormalizeTests(SimpleTestCase):
    def test_israeli_mobile_formats_are_unified(self):
        for raw in ["050-123-4567", "0501234567", "+972 50 123 4567", "972501234567", "00972-50-1234567",
                    "+972 (0)50 1234567", "501234567", "501234567.0", " 050 1234567 "]:
            with self.subTest(raw=raw):
                self.assertEqual(phones.normalize(raw), "0501234567")

    def test_landline_without_leading_zero_from_excel(self):
        self.assertEqual(phones.normalize("26234567"), "026234567")
        self.assertEqual(phones.normalize("02-623-4567"), "026234567")

    def test_palestinian_numbers(self):
        self.assertEqual(phones.normalize("+970599123456"), "0599123456")
        self.assertEqual(phones.whatsapp_number("0599123456"), "970599123456")

    def test_foreign_number_kept_international(self):
        self.assertEqual(phones.normalize("+1 202 555 0123"), "+12025550123")
        self.assertEqual(phones.whatsapp_number("+1 202 555 0123"), "12025550123")

    def test_empty_values(self):
        for raw in [None, "", "   ", "abc"]:
            with self.subTest(raw=raw):
                self.assertEqual(phones.normalize(raw), "")

    def test_display_and_links(self):
        self.assertEqual(phones.display("+972501234567"), "050-123-4567")
        self.assertEqual(phones.display("026234567"), "02-623-4567")
        self.assertEqual(phones.tel_href("050-123-4567"), "tel:0501234567")
        self.assertEqual(phones.whatsapp_url("0501234567", "مرحبا"), "https://wa.me/972501234567?text=%D9%85%D8%B1%D8%AD%D8%A8%D8%A7")
        self.assertTrue(phones.is_mobile("0501234567"))
        self.assertFalse(phones.is_mobile("026234567"))
