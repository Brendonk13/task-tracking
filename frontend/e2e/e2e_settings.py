"""
Django settings for the Playwright e2e run.

Identical to config.settings except the database, which is a throwaway SQLite
file under frontend/e2e/.tmp/ so the smoke test never touches backend/db.sqlite3.
playwright.config.ts deletes the file before running migrations, so every run
starts from an empty database with only the seeded built-in statuses.

Selected with DJANGO_SETTINGS_MODULE=e2e_settings and PYTHONPATH=<frontend>/e2e.
"""

from pathlib import Path

from config.settings import *  # noqa: F401,F403

E2E_DIR = Path(__file__).resolve().parent
E2E_DB_PATH = E2E_DIR / ".tmp" / "e2e.sqlite3"
E2E_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": E2E_DB_PATH,
    }
}
