"""
إعدادات نظام TBT CRM.

القيم الحساسة (المفتاح السري، وضع التطوير، أسماء النطاقات) تُقرأ من متغيرات البيئة
حتى لا تُحفظ داخل الكود. انظر الملف .env.example
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# مجلد البيانات: قاعدة البيانات، الملفات المرفوعة، والمفتاح السري
DATA_DIR = Path(os.environ.get("TBT_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_secret_key():
    """المفتاح السري من متغير البيئة، أو يُنشأ تلقائياً مرة واحدة ويُحفظ في مجلد البيانات."""
    key = os.environ.get("DJANGO_SECRET_KEY", "").strip()
    if key:
        return key
    key_file = DATA_DIR / "secret_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    from django.core.management.utils import get_random_secret_key

    key = get_random_secret_key()
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


# --- الأمان -------------------------------------------------------------------
# وضع التطوير مغلق افتراضياً. للتطوير فقط: DJANGO_DEBUG=1
DEBUG = env_bool("DJANGO_DEBUG", default=False)
SECRET_KEY = load_secret_key()

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if env_bool("DJANGO_HTTPS", default=False):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # أسبوعان
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# --- التطبيقات -----------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "crm",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "tbt_crm.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "crm.context_processors.crm_context",
            ],
            "builtins": ["crm.templatetags.crm_tags"],
        },
    },
]

WSGI_APPLICATION = "tbt_crm.wsgi.application"

# --- قاعدة البيانات --------------------------------------------------------------
# SQLite تكفي تماماً لفريق صغير. الملف يُحفظ في مجلد data حتى يسهل نسخه احتياطياً.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "tbt_crm.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "crm.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- اللغة والوقت --------------------------------------------------------------
LANGUAGE_CODE = "ar"
TIME_ZONE = os.environ.get("TBT_TIME_ZONE", "Asia/Jerusalem")
USE_I18N = True
USE_TZ = True
# تنسيقات أرقام وتواريخ مناسبة (نقطة عشرية، تاريخ يوم/شهر/سنة، ساعة 24)
FORMAT_MODULE_PATH = ["tbt_crm.formats"]
USE_THOUSAND_SEPARATOR = False

# --- الملفات الثابتة والمرفوعة ----------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = DATA_DIR / "uploads"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

MESSAGE_TAGS = {40: "danger"}  # messages.ERROR -> صنف Bootstrap

# --- إعدادات خاصة بـ TBT ----------------------------------------------------------
TBT = {
    "COMPANY_NAME": os.environ.get("TBT_COMPANY_NAME", "TBT"),
    # رمز الدولة الافتراضي لروابط واتساب (إسرائيل)
    "DEFAULT_COUNTRY_CODE": os.environ.get("TBT_COUNTRY_CODE", "972"),
    # بادئات أرقام فلسطينية تُرسل على واتساب برمز 970
    "PREFIX_COUNTRY_OVERRIDES": {"059": "970", "056": "970"},
    # عدد المحاولات بدون رد قبل إيقاف الاتصال بالعميل
    "MAX_UNANSWERED_ATTEMPTS": int(os.environ.get("TBT_MAX_ATTEMPTS", "5")),
    # كم يوماً قبل انتهاء عقد المنافس نتصل بالعميل
    "CONTRACT_FOLLOWUP_DAYS_BEFORE": 30,
    # بعد كم غياب عن الموعد يُنقل العميل لمتابعة بعد شهر
    "NO_SHOW_LIMIT": 2,
    "NO_SHOW_COOLDOWN_DAYS": 30,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
