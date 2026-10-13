import os
import tempfile

os.environ["SECRET_KEY"] = "test-only"
os.environ["DATABASE_URL"] = ""
os.environ["REDIS_URL"] = ""
os.environ["S3_BUCKET"] = ""
for _name in ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_EMBEDDING_MODEL", "CODEWEAVERS_LOGIN_URL",
              "CODEWEAVERS_USERNAME", "CODEWEAVERS_PASSWORD"):
    os.environ[_name] = ""

from .base import *  # noqa: E402,F401,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MEDIA_ROOT = tempfile.mkdtemp(prefix="hart-hub-test-media-")
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
ALERT_INBOUND_TOKEN = "test-inbound-token"
OPS_ALERT_EMAILS = ["ops@example.com"]
SYNC_ENABLED = {"motorway": True, "carwow": True, "bca": False, "manheim": True}
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405
