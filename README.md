# Task Tracking

A private, personal ticket tracker. Claude Code (or any LLM) sessions register
themselves, then post status changes, comments, and "needs human eyes" flags on
tickets over a small JSON API. The human opens the web UI to see what is blocked,
what needs a decision, and which session to resume to pick the work back up.

There is no auth. The app runs on your machine and is meant for one person.

## Run it

Prerequisites:

- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Node 22.12+ (24 recommended) and [`pnpm`](https://pnpm.io/) 11

```bash
git clone <this repo> && cd task-tracking
make dev
```

`make dev` runs two servers:

- Django + django-ninja backend on `http://localhost:8000` (it runs migrations first,
  which seeds the built-in statuses into `backend/db.sqlite3`).
- Vite dev server on `http://localhost:5173`, which proxies `/api` to the backend.

Open `http://localhost:5173` for the UI. The OpenAPI document is at
`http://localhost:8000/api/openapi.json` and interactive docs at
`http://localhost:8000/api/docs`.

Other targets:

| Command | What it does |
|---|---|
| `make test` | Backend `pytest`, then frontend `vitest` and `tsc` typecheck. |
| `make check-contract` | Regenerates `frontend/src/api/schema.d.ts` and fails if it differs from the committed file. |
| `make gen-api` | Regenerates the TypeScript API types from the backend (see "Type flow"). |
| `make e2e` | Playwright smoke test against a real backend (`frontend/e2e/`, task 8.1). It starts its own Django on `:8000` and Vite on `:5180` with a throwaway SQLite DB under `frontend/e2e/.tmp/` (`reuseExistingServer: false`), so stop `make dev` first or the backend port collides. Run `cd frontend && pnpm exec playwright install chromium` once before the first run. |

## For LLM sessions: how to register yourself and post

Every write to a ticket carries an `actor_session_id`. The server rejects an id it has
not seen with `400 {"detail": "unknown actor"}`. So a session registers first, then posts.
The reserved actor id `human` is always accepted and is what the UI uses.

The flow a Claude Code session follows:

1. **Register (or refresh) yourself.** `PUT /api/sessions/{session_id}` with your own
   session id in the path and `directory`, `last_message`, `last_message_at` in the body.
   The call is idempotent. The first call generates a short `name` (for example
   `sunny-crane`); later calls keep that name and update the other fields. Omitted keys
   are kept; an explicit `null` clears `last_message` or `last_message_at`. `directory`
   is required every time. The UI builds the resume command
   `cd <directory> && claude --resume <session_id>` from these fields, so keep them accurate.
2. **Create a ticket, or find one.** `POST /api/tickets` returns `201` with the new ticket
   and its `id`. `GET /api/tickets` lists existing tickets.
3. **Set the status with a reason.** `POST /api/tickets/{id}/status` with
   `{status, reason, actor_session_id}`. `reason` is required. Use a built-in status name
   or any new string; unknown names become custom statuses on first use.
4. **Comment.** `POST /api/tickets/{id}/comments` with `{body, actor_session_id}`.
5. **Ask for a human.** `POST /api/tickets/{id}/needs-human-eyes` with
   `{value, reason?, actor_session_id}`. `value: true` sets the flag; `false` clears it.
   This drives the red badge in the sidebar and the `needs_human_eyes=true` filter.

Rules that apply to every mutating ticket endpoint:

- The server checks in this order: `422` (invalid body) → `404` (no such ticket) →
  `400` (unknown actor).
- Every mutation returns `200` with the full `TicketDetail`, including the whole
  `timeline`. `POST /api/tickets` returns `201` with the same shape.
- No-ops (same status again, same flag value, PATCH that changes nothing) return `200`
  and write no timeline entry.
- Timestamps are ISO 8601 UTC with a `Z` suffix.

The ten built-in statuses, in the order the API and UI list them:

`blocked`, `needs-help`, `planning`, `implementing-plan`, `diagnosing-ticket`,
`needs-clarification`, `ready-for-pr`, `merged`, `tested-in-cloud`, `done`

A minimal end-to-end script:

```bash
API=http://localhost:8000/api
SID=0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f      # your Claude Code session id

curl -s -X PUT $API/sessions/$SID -H 'Content-Type: application/json' \
  -d '{"directory":"/home/me/code/avantos","last_message":"Fix the login redirect bug","last_message_at":"2026-09-12T10:00:00Z"}'

TID=$(curl -s -X POST $API/tickets -H 'Content-Type: application/json' \
  -d "{\"title\":\"Fix login redirect\",\"priority\":\"high\",\"actor_session_id\":\"$SID\"}" | jq .id)

curl -s -X POST $API/tickets/$TID/status -H 'Content-Type: application/json' \
  -d "{\"status\":\"blocked\",\"reason\":\"Need the staging credentials\",\"actor_session_id\":\"$SID\"}"

curl -s -X POST $API/tickets/$TID/comments -H 'Content-Type: application/json' \
  -d "{\"body\":\"Root cause is a stale refresh token in the cookie.\",\"actor_session_id\":\"$SID\"}"

curl -s -X POST $API/tickets/$TID/needs-human-eyes -H 'Content-Type: application/json' \
  -d "{\"value\":true,\"reason\":\"Need a decision on cookie lifetime\",\"actor_session_id\":\"$SID\"}"
```

## API reference

All paths are under `http://localhost:8000/api`. All bodies are JSON. The examples below
were run against a fresh database; ids, names, and timestamps will differ for you.

### Sessions

#### `PUT /api/sessions/{session_id}`

Register or update a session. Body: `directory` (required), `last_message`,
`last_message_at` (both optional, nullable). Returns `200` with the `Session`.

```bash
curl -s -X PUT http://localhost:8000/api/sessions/0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f \
  -H 'Content-Type: application/json' \
  -d '{"directory":"/home/me/code/avantos","last_message":"Fix the login redirect bug","last_message_at":"2026-09-12T10:00:00Z"}'
```

```json
{
  "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f",
  "name": "sunny-crane",
  "directory": "/home/me/code/avantos",
  "last_message": "Fix the login redirect bug",
  "last_message_at": "2026-09-12T10:00:00Z",
  "created_at": "2026-09-13T04:21:36.822Z"
}
```

Calling it again with only `last_message` keeps `name` and `last_message_at`:

```bash
curl -s -X PUT http://localhost:8000/api/sessions/0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f \
  -H 'Content-Type: application/json' \
  -d '{"directory":"/home/me/code/avantos","last_message":"now run the linter"}'
```

```json
{
  "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f",
  "name": "sunny-crane",
  "last_message": "now run the linter",
  "last_message_at": "2026-09-12T10:00:00Z",
  "...": "..."
}
```

#### `GET /api/sessions`

All sessions, most recent `last_message_at` first (sessions with no `last_message_at`
come last, newest `created_at` first among them).

```bash
curl -s http://localhost:8000/api/sessions
```

```json
[
  {
    "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f",
    "name": "sunny-crane",
    "directory": "/home/me/code/avantos",
    "last_message": "now run the linter",
    "last_message_at": "2026-09-12T10:00:00Z",
    "created_at": "2026-09-13T04:21:36.822Z"
  },
  {
    "session_id": "second-session",
    "name": "neat-finch",
    "directory": "/home/me/code/other",
    "last_message": null,
    "last_message_at": null,
    "created_at": "2026-09-13T04:21:36.828Z"
  }
]
```

### Statuses

#### `GET /api/statuses`

Built-in statuses in canonical order, then custom statuses sorted by name.

```bash
curl -s http://localhost:8000/api/statuses
```

```json
[
  { "name": "blocked", "is_builtin": true },
  { "name": "needs-help", "is_builtin": true },
  { "name": "planning", "is_builtin": true },
  { "name": "implementing-plan", "is_builtin": true },
  { "name": "diagnosing-ticket", "is_builtin": true },
  { "name": "needs-clarification", "is_builtin": true },
  { "name": "ready-for-pr", "is_builtin": true },
  { "name": "merged", "is_builtin": true },
  { "name": "tested-in-cloud", "is_builtin": true },
  { "name": "done", "is_builtin": true },
  { "name": "waiting-on-vendor", "is_builtin": false }
]
```

### Tickets

Two response shapes are used. `TicketListItem` is one row of the list:

```
id, title, priority, status, needs_human_eyes, linear_url, project, labels, created_at, updated_at
```

`TicketDetail` is `TicketListItem` plus `description` and `timeline`. Every timeline entry
has the same flat shape:

```
id, kind, actor {session_id, name, directory}, body, created_at, from_status, to_status, reason
```

`kind` is one of `comment`, `status_change`, `flag_change`, `field_change`. Fields that do
not apply to a kind are `null`. `priority` is one of `urgent`, `high`, `medium`, `low`,
`none` (default `none`). `status` is `null` until the first status change. `labels` are
always de-duplicated and sorted. The `timeline` is ordered oldest first.

#### `POST /api/tickets`

Create a ticket. Body: `title` (required), `description` (default `""`), `priority`,
`linear_url`, `project`, `labels`, `actor_session_id` (required). Returns `201` with
`TicketDetail`. Status and the needs-human-eyes flag cannot be set here; use the
endpoints below.

```bash
curl -s -X POST http://localhost:8000/api/tickets -H 'Content-Type: application/json' \
  -d '{"title":"Fix login redirect","description":"Users get a 500 after token refresh.","priority":"high","linear_url":"https://linear.app/avantos/issue/AVA-123/fix-login","project":"avantos","labels":["infra","ai"],"actor_session_id":"0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f"}'
```

```json
{
  "id": 1,
  "title": "Fix login redirect",
  "priority": "high",
  "status": null,
  "needs_human_eyes": false,
  "linear_url": "https://linear.app/avantos/issue/AVA-123/fix-login",
  "project": "avantos",
  "labels": ["ai", "infra"],
  "created_at": "2026-09-13T04:21:36.835Z",
  "updated_at": "2026-09-13T04:21:36.835Z",
  "description": "Users get a 500 after token refresh.",
  "timeline": []
}
```

With an unregistered actor:

```bash
curl -s -i -X POST http://localhost:8000/api/tickets -H 'Content-Type: application/json' \
  -d '{"title":"Nope","actor_session_id":"not-registered"}'
```

```
HTTP/1.1 400 Bad Request
{"detail": "unknown actor"}
```

#### `GET /api/tickets`

List tickets as `TicketListItem[]` (a plain array). Query parameters:

| Param | Values | Notes |
|---|---|---|
| `status` | any status name, repeatable | `?status=blocked&status=needs-help` returns tickets in either status (OR). Unknown names match nothing. |
| `needs_human_eyes` | `true` / `false` | Omit to return both. |
| `sort` | `created_at` (default), `updated_at`, `priority` | `priority` orders `urgent > high > medium > low > none`. `updated_at` bumps on every non-no-op mutation, including comments, so it means "recent activity". |
| `order` | `desc` (default), `asc` | Ties break on `created_at`, then `id`, in the same direction. |

```bash
curl -s 'http://localhost:8000/api/tickets?status=blocked&status=needs-help'
```

```json
[
  {
    "id": 1,
    "title": "Fix login redirect",
    "priority": "urgent",
    "status": "blocked",
    "needs_human_eyes": false,
    "linear_url": null,
    "project": "avantos",
    "labels": ["ai", "docs"],
    "created_at": "2026-09-13T04:21:36.835Z",
    "updated_at": "2026-09-13T04:21:36.886Z"
  }
]
```

```bash
curl -s 'http://localhost:8000/api/tickets?needs_human_eyes=true'
curl -s 'http://localhost:8000/api/tickets?sort=priority&order=desc'
curl -s 'http://localhost:8000/api/tickets?sort=updated_at&order=desc'
```

#### `GET /api/tickets/summary`

Count of tickets with `needs_human_eyes: true`. The sidebar badge reads this.

```bash
curl -s http://localhost:8000/api/tickets/summary
```

```json
{ "needs_human_eyes_count": 1 }
```

#### `GET /api/tickets/{id}`

One ticket as `TicketDetail`. Unknown id returns `404`.

```bash
curl -s http://localhost:8000/api/tickets/1
```

```json
{
  "id": 1,
  "title": "Fix login redirect",
  "priority": "urgent",
  "status": "blocked",
  "needs_human_eyes": true,
  "linear_url": null,
  "project": "avantos",
  "labels": ["ai", "docs"],
  "created_at": "2026-09-13T04:21:36.835Z",
  "updated_at": "2026-09-13T04:21:36.877Z",
  "description": "Users get a 500 after token refresh.",
  "timeline": [
    {
      "id": 4,
      "kind": "status_change",
      "actor": { "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f", "name": "sunny-crane", "directory": "/home/me/code/avantos" },
      "body": "sunny-crane set status to planning",
      "created_at": "2026-09-13T04:21:36.861Z",
      "from_status": null,
      "to_status": "planning",
      "reason": "Reading the auth code first"
    },
    {
      "id": 5,
      "kind": "status_change",
      "actor": { "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f", "name": "sunny-crane", "directory": "/home/me/code/avantos" },
      "body": "sunny-crane changed status from planning to blocked",
      "created_at": "2026-09-13T04:21:36.868Z",
      "from_status": "planning",
      "to_status": "blocked",
      "reason": "Need the staging credentials"
    },
    {
      "id": 6,
      "kind": "comment",
      "actor": { "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f", "name": "sunny-crane", "directory": "/home/me/code/avantos" },
      "body": "Root cause is a stale refresh token in the cookie.",
      "created_at": "2026-09-13T04:21:36.872Z",
      "from_status": null,
      "to_status": null,
      "reason": null
    },
    {
      "id": 7,
      "kind": "flag_change",
      "actor": { "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f", "name": "sunny-crane", "directory": "/home/me/code/avantos" },
      "body": "sunny-crane flagged needs human eyes",
      "created_at": "2026-09-13T04:21:36.878Z",
      "from_status": null,
      "to_status": null,
      "reason": "Need a decision on cookie lifetime"
    }
  ]
}
```

```
HTTP/1.1 404 Not Found
{"detail": "Not Found: No Ticket matches the given query."}
```

#### `PATCH /api/tickets/{id}`

Edit fields. Body: any of `title`, `description`, `priority`, `linear_url`, `project`,
`labels`, plus `actor_session_id` (required). Semantics:

- Per-key replace. Keys you omit are untouched.
- `labels` replaces the whole list. `[]` clears it.
- An explicit `null` clears `project` or `linear_url`. `null` on `title`, `description`,
  `priority`, or `labels` is rejected with `422`.
- One `field_change` timeline entry is written per field whose value actually changed,
  with body `<name> changed <field> from <old> to <new>`. Empty values render as `(none)`;
  lists render as `a, b`. A description edit writes `<name> changed description` with no
  values. A PATCH that changes nothing writes nothing.

```bash
curl -s -X PATCH http://localhost:8000/api/tickets/1 -H 'Content-Type: application/json' \
  -d '{"priority":"urgent","labels":["ai","docs"],"linear_url":null,"actor_session_id":"0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f"}'
```

```json
{
  "id": 1,
  "priority": "urgent",
  "linear_url": null,
  "labels": ["ai", "docs"],
  "timeline": [
    { "id": 1, "kind": "field_change", "body": "sunny-crane changed priority from high to urgent", "...": "..." },
    { "id": 2, "kind": "field_change", "body": "sunny-crane changed linear_url from https://linear.app/avantos/issue/AVA-123/fix-login to (none)", "...": "..." },
    { "id": 3, "kind": "field_change", "body": "sunny-crane changed labels from ai, infra to ai, docs", "...": "..." }
  ],
  "...": "..."
}
```

#### `POST /api/tickets/{id}/status`

Set the current status. Body: `status` (required, non-empty; surrounding whitespace is
stripped; case-sensitive), `reason` (required, non-empty), `actor_session_id` (required).
The server records the previous status as `from_status`. A status name that does not
exist yet is created as a custom status. Setting the status a ticket already has returns
`200` and writes nothing.

```bash
curl -s -X POST http://localhost:8000/api/tickets/1/status -H 'Content-Type: application/json' \
  -d '{"status":"planning","reason":"Reading the auth code first","actor_session_id":"0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f"}'
```

```json
{
  "id": 1,
  "status": "planning",
  "timeline": [
    {
      "id": 4,
      "kind": "status_change",
      "actor": { "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f", "name": "sunny-crane", "directory": "/home/me/code/avantos" },
      "body": "sunny-crane set status to planning",
      "created_at": "2026-09-13T04:21:36.861Z",
      "from_status": null,
      "to_status": "planning",
      "reason": "Reading the auth code first"
    }
  ],
  "...": "..."
}
```

A second change writes `sunny-crane changed status from planning to blocked` with
`from_status: "planning"`, `to_status: "blocked"`.

Without `reason`:

```
HTTP/1.1 422 Unprocessable Entity
{"detail": [{"type": "missing", "loc": ["body", "payload", "reason"], "msg": "Field required"}]}
```

#### `POST /api/tickets/{id}/comments`

Add a comment. Body: `body` (required, non-empty), `actor_session_id` (required). The
comment body is stored verbatim.

```bash
curl -s -X POST http://localhost:8000/api/tickets/1/comments -H 'Content-Type: application/json' \
  -d '{"body":"Looks right, go ahead.","actor_session_id":"human"}'
```

```json
{
  "id": 1,
  "timeline": [
    {
      "id": 8,
      "kind": "comment",
      "actor": { "session_id": "human", "name": "human", "directory": null },
      "body": "Looks right, go ahead.",
      "created_at": "2026-09-13T04:21:36.882Z",
      "from_status": null,
      "to_status": null,
      "reason": null
    }
  ],
  "...": "..."
}
```

#### `POST /api/tickets/{id}/needs-human-eyes`

Set or clear the flag. Body: `value` (boolean, required), `reason` (optional),
`actor_session_id` (required). Writes a `flag_change` entry with body
`<name> flagged needs human eyes` or `<name> cleared needs human eyes`. Setting the flag
to the value it already has returns `200` and writes nothing.

```bash
curl -s -X POST http://localhost:8000/api/tickets/1/needs-human-eyes -H 'Content-Type: application/json' \
  -d '{"value":true,"reason":"Need a decision on cookie lifetime","actor_session_id":"0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f"}'
```

```json
{
  "id": 1,
  "needs_human_eyes": true,
  "timeline": [
    {
      "id": 7,
      "kind": "flag_change",
      "actor": { "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f", "name": "sunny-crane", "directory": "/home/me/code/avantos" },
      "body": "sunny-crane flagged needs human eyes",
      "created_at": "2026-09-13T04:21:36.878Z",
      "from_status": null,
      "to_status": null,
      "reason": "Need a decision on cookie lifetime"
    }
  ],
  "...": "..."
}
```

Clearing it from the UI (`actor_session_id: "human"`, `value: false`) appends
`human cleared needs human eyes`.

### Errors

| Code | When | Body |
|---|---|---|
| `422` | Body fails validation (missing field, empty `reason`/`body`/`status`, `null` on a non-nullable PATCH field, bad `priority`, bad `sort`/`order`). | `{"detail": [ ...pydantic errors... ]}` (a list) |
| `404` | Ticket id does not exist. | `{"detail": "Not Found: No Ticket matches the given query."}` |
| `400` | `actor_session_id` is not a registered session and not `human`. | `{"detail": "unknown actor"}` |

The checks run in that order, so a bad body on a missing ticket is `422`, and an unknown
actor on a missing ticket is `404`.

## Project layout

```
task-tracking/
  Makefile                      # dev, test, gen-api, check-contract, e2e
  PLAN.md                       # the TDD build plan
  docs/ARCHITECT_MEMO.md        # binding amendments A1-A16 to the plan
  .github/workflows/ci.yml      # backend, frontend, contract jobs
  backend/                      # Django 6 + django-ninja + SQLite, managed by uv
    manage.py
    config/settings.py, urls.py # api mounted at /api
    tracker/
      models.py                 # Ticket, Tag, Status, Session, TimelineEntry
      schemas.py                # request/response schemas (the OpenAPI source of truth)
      api/tickets.py, sessions.py, statuses.py
      services/actors.py, tags.py, names.py
      migrations/               # 0007 seeds the ten built-in statuses
      tests/                    # pytest, HTTP through ninja's TestClient
  frontend/                     # Vite + React 19 + TypeScript + Tailwind + shadcn, managed by pnpm
    openapi.json                # exported from the backend by make gen-api (gitignored)
    e2e/                        # Playwright smoke test
    src/
      api/schema.d.ts           # GENERATED from openapi.json, never hand-edited
      api/client.ts             # openapi-fetch client typed by schema.d.ts
      api/hooks/                # react-query hooks, one file per resource
      components/layout/        # AppShell, Sidebar (badge from /api/tickets/summary)
      pages/                    # TicketListPage, TicketDetailPage, SessionsPage
      test/                     # Vitest setup, MSW server and handlers
```

### Type flow

The backend schemas are the single source of truth for API types. Nothing on the frontend
is typed by hand.

```
backend/tracker/schemas.py
  -> make gen-api
     1. uv run python manage.py export_openapi_schema --api tracker.api.api
          --output ../frontend/openapi.json          (no server needed)
     2. pnpm gen:api  ==  openapi-typescript openapi.json -o src/api/schema.d.ts
  -> frontend/src/api/schema.d.ts   (committed; generated; never hand-edited)
  -> frontend/src/api/client.ts     (openapi-fetch, fully typed)
  -> frontend/src/api/hooks/*.ts    (react-query)
```

`frontend/openapi.json` is gitignored. `frontend/src/api/schema.d.ts` is committed.
After any backend change that touches a schema or endpoint, run `make gen-api` and commit
the regenerated `schema.d.ts`. `make check-contract` does the same generation and then
`git diff --exit-code frontend/src/api/schema.d.ts`; CI runs it and fails the build if
the committed file is stale.
