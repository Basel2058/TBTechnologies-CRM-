"""تشغيل نظام TBT CRM بأمر واحد:  python run.py

- يجهّز قاعدة البيانات (أو يحدّثها بعد تنزيل نسخة جديدة).
- في أول تشغيل يطلب إنشاء حساب المدير.
- يشغّل النظام ويطبع العنوان الذي تفتحه في المتصفح.

Run TBT CRM with one command: python run.py
"""

import os
import socket
import sys
from getpass import getpass

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tbt_crm.settings")
# داخل شبكة المكتب: اسمح بالدخول عبر عنوان IP لهذا الكمبيوتر
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "*")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except OSError:
        return None


def ensure_manager():
    from crm.models import User

    if User.objects.exists():
        return
    username = os.environ.get("TBT_ADMIN_USERNAME", "").strip()
    password = os.environ.get("TBT_ADMIN_PASSWORD", "")
    if username and password:
        User.objects.create_superuser(username=username, password=password)
        print(f"Created manager account: {username}")
        return
    if not sys.stdin.isatty():
        print("No accounts yet. Create the manager account with: python manage.py createsuperuser")
        return

    print("\n=== First run: create the manager account / أول تشغيل: إنشاء حساب المدير ===")
    while True:
        username = input("Username (English letters) / اسم الدخول: ").strip()
        if username and username.isascii() and " " not in username:
            break
        print("Use English letters and numbers, no spaces.")
    first_name = input("Your name / اسمك: ").strip()
    while True:
        password = getpass("Password (8+ characters) / كلمة المرور: ")
        if len(password) < 8:
            print("Too short (8 characters at least).")
            continue
        if password != getpass("Repeat password / أعد كتابتها: "):
            print("Passwords do not match.")
            continue
        break
    User.objects.create_superuser(username=username, password=password, first_name=first_name)
    print("Manager account created.\n")


def main():
    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
    call_command("collectstatic", interactive=False, verbosity=0)
    ensure_manager()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    ip = lan_ip()
    print("=" * 60)
    print("TBT CRM is running / النظام يعمل")
    print(f"  On this computer:      http://localhost:{port}")
    if ip:
        print(f"  From the office network: http://{ip}:{port}")
    print("  Keep this window open. Close it to stop the system.")
    print("=" * 60)

    from waitress import serve

    from tbt_crm.wsgi import application

    serve(application, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
