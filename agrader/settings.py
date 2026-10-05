"""Django settings for AGRADER.

All secrets and deployment-specific values come from environment variables. Locally they are
loaded from `.env`; set AGRADER_ENV_FILE to load a different file (for example the production
values when running `manage.py prod_setup`). On Vercel they come from the project settings.
See `.env.example` and the README.
"""
import os
import sys
import warnings
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

_env_file = os.environ.get("AGRADER_ENV_FILE")
if _env_file:
    # An explicitly named file must exist: silently falling back to .env could point a
    # production command at the local database, or the reverse.
    if not Path(_env_file).is_file():
        raise ImproperlyConfigured(f"AGRADER_ENV_FILE={_env_file} does not exist.")
    load_dotenv(_env_file, override=True)
elif os.environ.get("VERCEL_ENV") not in ("production", "preview"):
    # Never read a local .env on a deployed host: one uploaded by mistake could switch on DEBUG.
    load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


TESTING = sys.argv[1:2] == ["test"]
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "insecure-local-development-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false. On Vercel, add it to the project's "
            "environment variables for every environment that builds (Production and Preview): the build "
            "imports these settings to run collectstatic."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Vercel sets these system variables on every deployment; trust them automatically.
for _var in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    _host = os.environ.get(_var, "").strip()
    if _host:
        ALLOWED_HOSTS.append(_host)
        CSRF_TRUSTED_ORIGINS.append(f"https://{_host}")

# Product name shown everywhere in the UI. Never hardcode it in templates.
PRODUCT_NAME = os.environ.get("PRODUCT_NAME", "AGRADER")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "accounts",
    "audit",
    "farms",
    "crops",
    "readings",
    "recommendations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves static files when requests reach Django (local `vercel dev`, other hosts).
    # On Vercel itself static files are served from the CDN and never reach this.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every screen requires login unless the view opts out explicitly.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "audit.middleware.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "agrader.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.product",
            ],
        },
    },
]

WSGI_APPLICATION = "agrader.wsgi.application"

# --- Database ---
# SQLite is for local development only. A serverless host has no lasting disk, so without
# DATABASE_URL production would silently lose every write: refuse to start instead.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if env_bool("AGRADER_DIRECT_DB") and os.environ.get("DATABASE_URL_UNPOOLED", "").strip():
    # Migrations are safer over a direct connection than through a transaction-mode pooler.
    DATABASE_URL = os.environ["DATABASE_URL_UNPOOLED"].strip()
if not DATABASE_URL and not (DEBUG or TESTING):
    raise ImproperlyConfigured("DATABASE_URL must be set when DJANGO_DEBUG is false.")
DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        # Serverless functions start and stop often; keeping connections open across requests
        # mostly leaves idle connections behind. 0 closes each connection after the request.
        conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "0")),
        conn_health_checks=True,
    )
}
# Transaction-mode poolers (PgBouncer, Neon "-pooler" hosts, Supabase port 6543) do not
# support server-side cursors.
if env_bool("DB_POOLED", False):
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "overview"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Lagos"
USE_I18N = False
USE_TZ = True

# --- Static files ---
# Vercel runs collectstatic during the build and serves STATIC_ROOT from its CDN.
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_USE_FINDERS = True
# STATIC_ROOT only exists after collectstatic (the Vercel build); locally the finders serve files.
warnings.filterwarnings("ignore", message="No directory at: .*staticfiles")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- HTTPS (production sits behind Vercel's proxy, which terminates TLS) ---
if not DEBUG and not TESTING:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
    SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# --- Logging: everything to stdout, which is what the host's log viewer shows ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

# --- Recommendation engine (used from phase 6) ---
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "")
ALLOW_UNAPPROVED_RULES = env_bool("ALLOW_UNAPPROVED_RULES", False)

if TESTING:
    # Fast password hashing (full-strength hashing makes the suite very slow).
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
