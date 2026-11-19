import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from crm import importer
from crm.models import Customer, Sector, User

MEDIA = tempfile.mkdtemp(prefix="tbt-test-media-")


def xlsx_bytes(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=MEDIA)
class ImportTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.manager = User.objects.create_user("boss", password="x", role=User.Role.ADMIN)
        self.agent = User.objects.create_user("agent", password="x", role=User.Role.AGENT)
        Customer.objects.create(business_name="موجود مسبقاً", phone="050-999-8877")
        self.client.force_login(self.manager)

    def upload(self, content, name, **extra):
        data = {"file": SimpleUploadedFile(name, content), "has_header": "on", "source": "imported", **extra}
        response = self.client.post(reverse("import_upload"), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        return response["Location"]

    def test_guess_mapping_in_three_languages(self):
        headers = ["اسم المصلحة", "الاسم", "جوال", "עיר", "Email", "نوع المصلحة", "ملاحظات"]
        self.assertEqual(importer.guess_mapping(headers, []),
                         ["business_name", "contact_name", "phone", "city", "email", "sector", "notes"])

    def test_phone_column_detected_without_headers(self):
        rows = [["صالون", "0501234567"], ["مطعم", "0527654321"]]
        self.assertEqual(importer.guess_mapping(["", ""], rows), ["", "phone"])

    def test_excel_import_end_to_end(self):
        content = xlsx_bytes([
            ["اسم المصلحة", "اسم صاحبها", "هاتف", "المدينة", "نوع المصلحة"],
            ["صالون ليالي", "رنا", 501234567, "الناصرة", "صالون / حلاقة / تجميل"],   # رقم بدون صفر كما يحفظه إكسل
            ["مطعم الزيتونة", "سامر", "+972-52-765-4321", "حيفا", "نوع جديد"],
            ["نسخة من ليالي", "", "050-123-4567", "", ""],                          # مكرر داخل الملف
            ["موجود", "", "972509998877", "", ""],                                   # موجود في النظام
            ["بدون رقم", "", "", "", ""],
        ])
        location = self.upload(content, "list.xlsx", assigned_to=self.agent.pk, tags="قائمة تشرين")
        page = self.client.get(location)
        self.assertContains(page, "اسم المصلحة")
        response = self.client.post(location, {"col_0": "business_name", "col_1": "contact_name", "col_2": "phone",
                                               "col_3": "city", "col_4": "sector"})
        result = response.context["result"]
        self.assertEqual(result["created"], 2)
        self.assertEqual(len(result["duplicates"]), 2)
        self.assertEqual(len(result["invalid"]), 1)
        laila = Customer.objects.get(business_name="صالون ليالي")
        self.assertEqual(laila.phone_normalized, "0501234567")
        self.assertEqual(laila.assigned_to, self.agent)
        self.assertEqual(laila.sector.name, "صالون / حلاقة / تجميل")
        self.assertIn("قائمة تشرين", laila.tags)
        self.assertTrue(Sector.objects.filter(name="نوع جديد").exists())
        self.assertTrue(laila.activities.exists())
        # الملف المؤقت حُذف بعد الاستيراد
        self.assertEqual(self.client.post(location, {"col_2": "phone"}).status_code, 302)

    def test_csv_windows_arabic_encoding(self):
        content = "الاسم;الهاتف\nأحمد;0541112233\n".encode("cp1256")
        location = self.upload(content, "list.csv")
        response = self.client.post(location, {"col_0": "contact_name", "col_1": "phone"})
        self.assertEqual(response.context["result"]["created"], 1)
        self.assertTrue(Customer.objects.filter(contact_name="أحمد", phone_normalized="0541112233").exists())

    def test_phone_column_is_required(self):
        location = self.upload(xlsx_bytes([["الاسم", "المدينة"], ["أحمد", "حيفا"]]), "list.xlsx")
        response = self.client.post(location, {"col_0": "contact_name", "col_1": "city"})
        self.assertContains(response, "يجب اختيار عمود «الهاتف»")

    def test_rejects_other_file_types(self):
        response = self.client.post(reverse("import_upload"), {
            "file": SimpleUploadedFile("list.pdf", b"%PDF"), "has_header": "on", "source": "imported",
        })
        self.assertContains(response, "الملف يجب أن يكون Excel")
