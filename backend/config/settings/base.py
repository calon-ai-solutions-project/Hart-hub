"""Settings shared by every environment. Secrets come from environment variables only."""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# backend/.env is for local development only; Railway injects real variables.
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
ADMIN_URL = env("ADMIN_URL", default="admin/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.listings",
    "apps.sourcing",
    "apps.ai",
    "apps.matching",
    "apps.chat",
    "apps.quotes",
    "apps.enquiries",
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
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
            ],
        },
    },
]

# ---------------------------------------------------------------- database

if env("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
    DATABASES["default"]["CONN_MAX_AGE"] = 60
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------- time

# Stored UTC; displayed and scheduled in Europe/London.
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
UK_TIME_ZONE = "Europe/London"

# ---------------------------------------------------------------- files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Where photos and quote documents are kept: Cloudinary, else an S3-compatible bucket, else backend/media.
CLOUDINARY_URL = env("CLOUDINARY_URL", default="")  # cloudinary://<api key>:<api secret>@<cloud name>
S3_BUCKET = env("S3_BUCKET", default="")
if CLOUDINARY_URL:
    _default_storage = {"BACKEND": "apps.core.storage.CloudinaryStorage"}
elif S3_BUCKET:
    _default_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": S3_BUCKET,
            "endpoint_url": env("S3_ENDPOINT", default=None),
            "access_key": env("S3_KEY"),
            "secret_key": env("S3_SECRET"),
            "region_name": env("S3_REGION", default=None),
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": 3600,
            "signature_version": "s3v4",
            "addressing_style": env("S3_ADDRESSING_STYLE", default=None),  # "virtual" or "path" if the host needs it
            "file_overwrite": True,
        },
    }
else:
    _default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Sync records carry every scraped field, so allow bodies larger than Django's 2.5 MB default.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
PHOTO_MAX_BYTES = 10 * 1024 * 1024
THUMBNAIL_PX = 480

# ---------------------------------------------------------------- cache and jobs

REDIS_URL = env("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
# Sessions are read from the cache and written through to the database: no session query per request.
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_TASK_ALWAYS_EAGER = not REDIS_URL  # no broker: run jobs inline
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = UK_TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "prepare-due-syncs": {"task": "sourcing.prepare_due_syncs", "schedule": crontab(minute="*/5")},
    "expire-listings": {"task": "listings.expire_listings", "schedule": crontab(minute="*/15")},
    "embed-listings": {"task": "listings.embed_pending", "schedule": crontab(minute="*/5")},
}

# ---------------------------------------------------------------- api

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"alerts_inbound": "60/min", "sync": "600/min", "chat": "120/min", "login": "10/min",
                               "public": "60/min", "public_photos": "600/min"},
}

# The address customers open (the web app). Car page links are built on it, e.g. <this>/c/7Kq2xYp9.
PUBLIC_SITE_URL = env("PUBLIC_SITE_URL", default="http://localhost:5173").rstrip("/")

# ---------------------------------------------------------------- ai

# The chatbot uses AI only when both are set; without them it falls back to rule-based matching.
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", default="")
OPENROUTER_MODEL = env("OPENROUTER_MODEL", default="")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Vector search is on only when the key and this model are set. Changing the model means
# re-embedding every car, and a model with a different vector length needs a migration.
OPENROUTER_EMBEDDING_MODEL = env("OPENROUTER_EMBEDDING_MODEL", default="")
OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
EMBEDDING_DIMENSIONS = 1536
EMBEDDING_BATCH = 64
AI_TIMEOUT_SECONDS = 30
AI_MAX_OUTPUT_TOKENS = 600  # answers are small JSON objects
# How much hidden "thinking" a model may do before it answers. Gemini thinks by default and, left alone,
# spends the whole answer allowance on it, so the JSON comes back cut off. Empty = send nothing.
AI_REASONING_EFFORT = env("AI_REASONING_EFFORT", default="minimal")

# ---------------------------------------------------------------- codeweavers (finance quotes)

# The Showroom login the Hub uses to get quotes. Codeweavers allows one session per login, so
# give the Hub its own user: signing in signs out anyone else using the same login.
CODEWEAVERS_LOGIN_URL = env("CODEWEAVERS_LOGIN_URL", default="")
CODEWEAVERS_USERNAME = env("CODEWEAVERS_USERNAME", default="")
CODEWEAVERS_PASSWORD = env("CODEWEAVERS_PASSWORD", default="")
# The JSON Finance API (the same login, HTTP basic auth). Settings row codeweavers_method picks api or browser.
CODEWEAVERS_API_URL = (env("CODEWEAVERS_API_URL", default="") or "https://services.codeweavers.net").rstrip("/")

# ---------------------------------------------------------------- platform sync (contract Schedule 1)

# A platform syncs only when its switch is on (written client approval).
SYNC_ENABLED = {
    platform: env.bool(f"SYNC_ENABLED_{platform.upper()}", default=False)
    for platform in ("motorway", "carwow", "bca", "manheim")
}
SYNC_DELAY_MS = env.int("SYNC_DELAY_MS", default=4000)
SYNC_STALE_RUN_HOURS = 6

# Shared secret for the inbound alert-email webhook.
ALERT_INBOUND_TOKEN = env("ALERT_INBOUND_TOKEN", default="")

# Who is told when a platform stops a run.
OPS_ALERT_EMAILS = env.list("OPS_ALERT_EMAILS", default=[])
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="hub@localhost")
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
