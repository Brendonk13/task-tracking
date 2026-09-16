"""
Django settings for the Task Tracking backend.

Local, private, single-user app. DEBUG stays on. The server is reachable from
this machine only: it binds to 127.0.0.1 (see the Makefile), ALLOWED_HOSTS lists
only loopback names, and LocalhostOnlyMiddleware rejects any peer that is not on
the loopback interface.

No CORS package: the Vite dev server proxies /api to this backend, so the
browser only ever talks to one origin.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Reads backend/.env, which is gitignored. Keeps ANTHROPIC_API_KEY out of the repo.
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SECRET_KEY = "django-insecure-task-tracking-local-dev-only"

DEBUG = True

# Loopback only. A request whose Host header names anything else gets a 400.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "ninja",
    "tracker",
]

MIDDLEWARE = [
    "config.middleware.LocalhostOnlyMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
