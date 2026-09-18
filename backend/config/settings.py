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

# ---- Crons (see README "Crons"). Every one of these is read from backend/.env.
# A missing value is never guessed: the cron step that needs it is skipped and
# records a `cron_error` alert naming the variable.

# Linear personal API key, used read-only over GraphQL.
LINEAR_API_KEY = os.environ.get("LINEAR_API_KEY", "")
# Issues assigned to this person are the ones imported.
LINEAR_ASSIGNEE_EMAIL = os.environ.get("LINEAR_ASSIGNEE_EMAIL", "")
# GitHub login whose open PRs are imported, and whose comments count as answers.
GITHUB_USER = os.environ.get("GITHUB_USER", "")
# Repositories to import PRs from, comma separated: "owner/repo,owner/other".
GITHUB_REPOS = [
    repo.strip() for repo in os.environ.get("GITHUB_REPOS", "").split(",") if repo.strip()
]


def _repo_dirs(raw: str) -> dict[str, str]:
    """Parse ``repo=path;repo=path`` into ``{repo: path}``."""
    pairs = {}
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        repo, _, path = entry.partition("=")
        pairs[repo.strip()] = path.strip()
    return pairs


# Local checkout a session for a PR in that repo runs in.
REPO_DIRS = _repo_dirs(os.environ.get("REPO_DIRS", ""))
# Directory the /ticket-brief skill writes briefs into.
BRIEFS_DIR = os.environ.get("BRIEFS_DIR", "")
# The Claude Code executable used to spawn headless sessions.
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_SESSION_TIMEOUT_SECONDS = int(
    os.environ.get("CLAUDE_SESSION_TIMEOUT_SECONDS", "1800")
)
CLAUDE_MAX_BUDGET_USD = float(os.environ.get("CLAUDE_MAX_BUDGET_USD", "5"))
# How many headless sessions one cron run may spawn, briefs and triage together.
CRON_MAX_SESSIONS_PER_RUN = int(os.environ.get("CRON_MAX_SESSIONS_PER_RUN", "3"))
# Scratch space for cron workers: logs and the triage analysis JSON.
CRON_WORK_DIR = os.environ.get("CRON_WORK_DIR", str(BASE_DIR / "var"))


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
