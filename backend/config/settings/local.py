import os
from pathlib import Path

import environ

# In local development backend/.env always wins, even over values the dev server inherited when it
# was first started, so an edit to .env takes effect on the next reload instead of being ignored.
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    environ.Env.read_env(_env_file, overwrite=True)
os.environ.setdefault("SECRET_KEY", "local-development-only")

from .base import *  # noqa: E402,F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
