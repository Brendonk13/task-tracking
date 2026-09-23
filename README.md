# Task Tracking

A private, personal ticket tracker. Claude Code (or any LLM) sessions register
themselves, then post status changes, comments, and "needs human eyes" flags on
tickets over a small JSON API. The human opens the web UI to see what is blocked,
what needs a decision, and which session to resume to pick the work back up.

There is no auth. The app runs on your machine and is meant for one person.
Instead of auth, it only accepts requests from localhost — three separate checks:

- Both servers bind to `127.0.0.1`, so nothing on your network can open a socket
  to them.
- `ALLOWED_HOSTS` is `localhost`, `127.0.0.1`, `[::1]`; any other `Host` header
  gets a `400`.
- `config.middleware.LocalhostOnlyMiddleware` rejects a request with `403` unless
  the peer address is on the loopback interface. It reads `REMOTE_ADDR`, the real
  socket peer, so a forged `X-Forwarded-For` does not get past it.

Do not run `manage.py runserver 0.0.0.0:8000` or `vite --host` to reach the app
from another device: there is no auth behind the localhost check.

## Run it

Prerequisites:

- Python 3.14 and [`uv`](https://docs.astral.sh/uv/)
- Node 22.12+ (24 recommended) and [`pnpm`](https://pnpm.io/) 11

```bash
git clone <this repo> && cd task-tracking
make install   # uv sync + pnpm install --frozen-lockfile
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
   Once you know which ticket you are on, PUT again with `ticket_id` so the sessions page
   shows what you are working on.
2. **Create a ticket, or find one.** `POST /api/tickets` returns `201` with the new ticket
   and its `id`. `GET /api/tickets` lists existing tickets. When you break work down, pass
   `parent_id` to create the pieces as sub-tickets of the ticket you were given (see
   "Sub-tickets"), so the decomposition outlives your session.
3. **Set the status with a reason.** `POST /api/tickets/{id}/status` with
   `{status, reason, actor_session_id}`. `reason` is required. Use a built-in status name
   or any new string; unknown names become custom statuses on first use.
4. **Comment.** `POST /api/tickets/{id}/comments` with `{body, actor_session_id}`.
5. **Ask for a human.** `POST /api/tickets/{id}/needs-human-eyes` with
   `{value, reason?, actor_session_id}`. `value: true` sets the flag; `false` clears it.
   This drives the red badge in the sidebar and the `needs_human_eyes=true` filter.
6. **Break the ticket into tasks.** `POST /api/tickets/{id}/tasks` with
   `{title, description?, depends_on?, actor_session_id}` for each small piece of work
   ("write the migration", "expose the endpoint"). `depends_on` is a list of task ids on the
   same ticket; the server rejects cycles, so the tasks always form a DAG. Move a task with
   `POST /api/tasks/{task_id}/state` (`todo` → `in_progress` → `done`, or `cancelled`). Each
   task keeps its own history. Pick the next task from `TicketDetail.tasks`: one in state
   `todo` whose `blocked_by` is empty is ready to start (see "Tasks").

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

curl -s -X PUT $API/sessions/$SID -H 'Content-Type: application/json' \
  -d "{\"directory\":\"/home/me/code/avantos\",\"ticket_id\":$TID}"

curl -s -X POST $API/tickets/$TID/status -H 'Content-Type: application/json' \
  -d "{\"status\":\"blocked\",\"reason\":\"Need the staging credentials\",\"actor_session_id\":\"$SID\"}"

curl -s -X POST $API/tickets/$TID/comments -H 'Content-Type: application/json' \
  -d "{\"body\":\"Root cause is a stale refresh token in the cookie.\",\"actor_session_id\":\"$SID\"}"

curl -s -X POST $API/tickets/$TID/needs-human-eyes -H 'Content-Type: application/json' \
  -d "{\"value\":true,\"reason\":\"Need a decision on cookie lifetime\",\"actor_session_id\":\"$SID\"}"
```

## Crons

The tracker also pulls work in on its own. One **cron run** is one pass over the outside
world, recorded as a `CronRun` row. A pass does four steps, always in this order:

1. **Import Linear tickets.** Active issues assigned to `LINEAR_ASSIGNEE_EMAIL` become
   tickets, with their identifier, priority, URL, project, and labels. An issue this app
   already has a ticket for is left alone. A ticket a human raised by hand and pasted the
   Linear URL into is adopted, not duplicated. Each new ticket raises a `new_ticket` alert.
2. **Write briefs.** Every imported ticket that has never been handed to a brief session
   gets one: a headless Claude Code session running `/ticket-brief`, opus, high effort. The
   session row is written before the process starts, so it is visible on the sessions page
   while it runs. The brief's `md_path` and `html_path` land on the ticket, and
   `GET /api/tickets/{id}/brief` serves the HTML.
3. **Import PRs.** Open pull requests by `GITHUB_USER` in `GITHUB_REPOS` are read with
   `gh`, together with their three comment feeds. Each PR is linked to the ticket whose
   Linear identifier appears in its branch, title, or body, and that link writes a
   `field_change` entry on the ticket's timeline under the `cron` actor. A PR that matches
   no ticket raises one `pr_unlinked` alert and does not raise it again until somebody
   dismisses it. A PR that has left the open listing is asked about by name, so its `state`
   becomes `merged` or `closed` rather than staying a stale `open`.
4. **Triage PR comments.** A PR with comments that are still waiting on you — not triaged,
   not written by `GITHUB_USER`, and in a thread you did not answer last — gets a headless
   `/github-pr-comment-triage` session in that repo's checkout. From its analysis the cron
   writes one gate task, `Human review of PR comment triage for PR #N`, one task per
   comment that needs a code change, and — when the triage drafted any replies — one task
   carrying all of them. Every one of those tasks depends on the gate, so nothing is
   startable until a human marks the gate done. The ticket goes to `blocked`, is flagged
   `needs_human_eyes`, and a `pr_triaged` alert is raised. A triage that judged nothing is
   an answer, not a failure: the comments are marked triaged, and the block, the flag and
   the alert are not spent on a quiet PR.

Steps are isolated from each other. A step whose configuration is incomplete is skipped
and writes a `cron_error` alert naming the variables; a step that raises writes a
`cron_error` alert quoting the error. Either way the following steps still run and the run
still ends `finished`, with a `summary` like `2 tickets, 1 brief, 3 pull requests, 1
triage` counting only the steps that actually ran.

### Single flight and the worker

`POST /api/crons/run` does not do the work. It records the run and starts a detached
worker, `manage.py run_cron <id>`, under the same interpreter, in its own process session
(`start_new_session=True`), with its output appended to
`<CRON_WORK_DIR>/crons/run-<id>.log`. Then it answers `202` with a run already `running`.

The work lives outside the web process for two reasons: a pass talks to Linear, GitHub and
Claude Code and takes minutes, which is far longer than a request should be held open; and
the dev server autoreloads, so a run inside it would be killed half-finished the next time
you save a file. Detaching the worker is what lets it survive that reload.

Only one pass runs at a time. A caller that arrives while one is in flight joins it: `200`
with the run already running, and no second worker. The check in the view is not what makes
this safe — the `one_running_cron_run` partial unique constraint is, so two callers racing
never both start a pass; the one the database refuses joins the other, or starts its own if
that one has already finished. Before that check, any run whose worker pid is no longer a live
process is reaped: marked `failed` with a `cron_error` alert saying the worker is gone, so
a machine that rebooted mid-run does not block the cron for ever.

### Safety guarantees

Everything the cron starts is read-only outside this app's own database.

- The Linear client has query methods only. It sends GraphQL queries and nothing else, so
  no cron run can write to Linear.
- GitHub is read through `gh pr list`, `gh pr view`, and `gh api` GETs. There is no
  code path that passes `-X`, `--method`, `-f`, `-F`, `--input`, or `graphql`.
- Spawned sessions run with `--permission-prompts none` plus explicit allow and deny lists.
  Both deny lists block `Bash(gh pr comment:*)`, `Bash(gh pr review:*)`, `Bash(gh api -X:*)`,
  `Bash(git commit:*)`, `Bash(git push:*)`, `Bash(git checkout:*)`, and the Linear
  `create_*`/`update_*`/`delete_*`/`save_*` tools. Triage also denies `Edit`, `MultiEdit`,
  `gh pr merge`/`close`, `gh api --method`/`-f`/`-F`/`--input`/`graphql`, and
  `git switch`/`stash`/`rebase`/`reset`, because it reads a checkout it must not disturb.
- The same rule is repeated in `--append-system-prompt`, in words the model reads:
  read-only on Linear, GitHub and Slack. A brief session may write only under `BRIEFS_DIR`
  and never inside the repository; a triage session writes only its analysis JSON under
  `<CRON_WORK_DIR>/triage/`.
- Drafted replies are never posted. They land in a task that is blocked by the human review
  gate, so a person reads them before anyone answers a reviewer.
- A run may start at most `CRON_MAX_SESSIONS_PER_RUN` sessions, briefs and triage sharing
  the one allowance, and every session runs under `--max-budget-usd` and a timeout. Work
  that does not fit is picked up by the next pass; it is deferred, never dropped.
- A triage that fails leaves its comments untriaged, writes no tasks, and does not block
  the ticket. The next pass retries it.

### Scheduling it

Either trigger works, and both end up in the same `execute`, so a run behaves the same
whichever asked for it. From the system crontab, every fifteen minutes:

```
*/15 * * * * curl -s -X POST http://127.0.0.1:8000/api/crons/run
```

Or in the foreground, without the web server:

```bash
cd backend && uv run python manage.py run_cron
```

With no argument the command records a new run (`trigger: command`; `--trigger api` says
otherwise) and does the work in the foreground. `run_cron <id>` executes a run that is
already recorded, which is what the detached worker is given. The command does not join a
run in flight the way the endpoint does: while one is running, the `one_running_cron_run`
constraint refuses the insert and the command fails.

### Configuration

Every variable below is read from `backend/.env` (copy `backend/.env.example`). Nothing is
guessed: when a variable a step needs is blank, that step is skipped and the run writes a
`cron_error` alert reading `Skipped <step>: set <VARIABLE>.`. The rest of the pass carries
on.

| Variable | What it is | Blank means |
|---|---|---|
| `LINEAR_API_KEY` | Linear personal API key, sent as the raw `Authorization` header. Used read-only. | Ticket import is skipped. |
| `LINEAR_ASSIGNEE_EMAIL` | Issues assigned to this person are the ones imported. | Ticket import is skipped. |
| `GITHUB_USER` | GitHub login whose open PRs are imported. Comments by this login count as answers, so they never become pending. | PR import and comment triage are skipped. |
| `GITHUB_REPOS` | Repos to import from, comma separated `owner/repo`. | PR import is skipped. |
| `REPO_DIRS` | Local checkout per repo, `repo=path;repo=path`. A brief session runs in the first one; a triage session runs in the one for its PR's repo. | Briefs and triage are skipped. A path that is not a directory skips both too, with one alert naming `REPO_DIRS` and the path. |
| `BRIEFS_DIR` | Where `/ticket-brief` writes briefs, and the only directory a brief session may write to. | Briefs are skipped. |
| `CLAUDE_BIN` | The Claude Code executable. Defaults to `claude`. | Briefs and triage are skipped. |
| `CLAUDE_SESSION_TIMEOUT_SECONDS` | Wall-clock limit per spawned session. Defaults to `1800`. | Never blank; a timed-out session is recorded `failed` with a `cron_error` alert. |
| `CLAUDE_MAX_BUDGET_USD` | `--max-budget-usd` per spawned session. Defaults to `5`. | Never blank. |
| `CRON_MAX_SESSIONS_PER_RUN` | How many sessions one run may start, briefs and triage together. Defaults to `3`. | Never blank. |
| `CRON_WORK_DIR` | Scratch space the cron owns: worker logs under `crons/`, triage analyses under `triage/`. Defaults to `backend/var`. | Triage is skipped. |

## API reference

All paths are under `http://localhost:8000/api`. All bodies are JSON. The examples below
were run against a fresh database; ids, names, and timestamps will differ for you.

### Sessions

#### `PUT /api/sessions/{session_id}`

Register or update a session. Body: `directory` (required), `last_message`,
`last_message_at`, `ticket_id` (all optional, nullable). Returns `200` with the `Session`.
The path id `human` is reserved for the UI actor and is rejected with `422`.

`ticket_id` is the ticket the session is working on, as the session itself last reported
it. It is advisory, not a claim: nothing stops two sessions from naming the same ticket.
An id that names no ticket is rejected with `400 {"detail": "unknown ticket"}`. Like the
other optional keys, omitting it keeps the stored value and an explicit `null` clears it.
The sessions page links to the ticket from each row.

Six fields describe sessions the backend started itself (see "Crons") and cannot be set
through this endpoint:

| Field | Values | Notes |
|---|---|---|
| `purpose` | `manual`, `ticket_brief`, `pr_triage` | `manual` for every session registered through this endpoint. |
| `model` | e.g. `opus`, or `null` | The model the cron launched the session with. `null` on a manual session. |
| `effort` | e.g. `high`, or `null` | The reasoning effort it was launched with. `null` on a manual session. |
| `status` | `running`, `finished`, `failed`, or `null` | How the spawned process ended. `null` on a manual session: nothing here watches it. |
| `result_summary` | string or `null` | The run's own one-line verdict, from its structured output. |
| `finished_at` | timestamp or `null` | When the process ended. |

The session id of a cron-started session is generated before the process starts, so
`claude --resume <session_id>` opens its transcript like any other.

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
  "ticket_id": null,
  "purpose": "manual",
  "model": null,
  "effort": null,
  "status": null,
  "result_summary": null,
  "finished_at": null,
  "created_at": "2026-09-13T04:21:36.822Z"
}
```

Calling it again with `directory` and a new `last_message` keeps `name` and
`last_message_at`:

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
    "ticket_id": 1,
    "purpose": "manual",
    "model": null,
    "effort": null,
    "status": null,
    "result_summary": null,
    "finished_at": null,
    "created_at": "2026-09-13T04:21:36.822Z"
  },
  {
    "session_id": "3a7f1d02-9c44-4a11-b0e6-2d5c8f31aa90",
    "name": "neat-finch",
    "directory": "/home/me/code/avantos",
    "last_message": "Wrote the brief for CON-7.",
    "last_message_at": "2026-09-13T04:26:02.104Z",
    "ticket_id": 3,
    "purpose": "ticket_brief",
    "model": "opus",
    "effort": "high",
    "status": "finished",
    "result_summary": "Bug in the handoff dispatcher; the task id is dropped before the retry.",
    "finished_at": "2026-09-13T04:26:02.104Z",
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
id, title, priority, status, needs_human_eyes, linear_url, linear_identifier, project,
labels, parent_id, created_at, updated_at
```

`linear_identifier` is the Linear key (`CON-7`), stored uppercase and unique. It is set by
the ticket import, or by the import adopting a ticket somebody raised by hand; the API
never accepts one in a request body, so it is `null` on a ticket that was only ever
created here.

`TicketDetail` is `TicketListItem` plus `description`, `parent`, `children`, `tasks`,
`timeline`, `brief` and `pull_requests`. `parent` is `{id, title}` or `null`; `children` is
a `TicketListItem[]`, oldest first; `tasks` is a `Task[]`, oldest first (see "Tasks").
`brief` is `{md_path, html_path}` or `null` — where a brief session wrote its two files;
the HTML itself comes from `GET /api/tickets/{id}/brief`. `pull_requests` is the PRs linked
to this ticket, each `{id, number, url, state}`, grouped by repo with the highest number
first (see "Pull requests").
Every timeline entry has the same flat shape:

```
id, kind, actor {session_id, name, directory}, body, created_at, from_status, to_status, reason
```

`kind` is one of `comment`, `status_change`, `flag_change`, `field_change`. Fields that do
not apply to a kind are `null`. `priority` is one of `urgent`, `high`, `medium`, `low`,
`none` (default `none`). `status` is `null` until the first status change. `labels` are
always de-duplicated and sorted. The `timeline` is ordered oldest first.

#### `POST /api/tickets`

Create a ticket. Body: `title` (required), `description` (default `""`), `priority`,
`linear_url`, `project`, `labels`, `parent_id`, `actor_session_id` (required). Returns `201` with
`TicketDetail`. Status and the needs-human-eyes flag cannot be set here; use the
endpoints below (`status` and `needs_human_eyes` keys in this body are silently
ignored). `title` is stripped and must be non-empty; blank `linear_url`/`project`
become `null`; `labels` are stripped, de-duplicated, and sorted with blanks dropped.

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
| `parent` | a ticket id | Returns the sub-tickets of that ticket. An unknown id matches nothing. |
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

(That is the `DEBUG=True` body; with `DEBUG=False` it is `{"detail": "Not Found"}`.)

#### `PATCH /api/tickets/{id}`

Edit fields. Body: any of `title`, `description`, `priority`, `linear_url`, `project`,
`labels`, `parent_id`, plus `actor_session_id` (required). Semantics:

- Per-key replace. Keys you omit are untouched.
- `labels` replaces the whole list. `[]` clears it.
- An explicit `null` clears `project`, `linear_url`, or `parent_id`. `null` on `title`, `description`,
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

#### Sub-tickets

A ticket can have one parent, set with `parent_id` on create or PATCH. The hierarchy is
**one level deep**: a sub-ticket cannot have sub-tickets of its own. `GET /api/tickets/{id}`
returns `parent` (`{id, title}` or `null`) and `children` (`TicketListItem[]`, oldest first);
`GET /api/tickets?parent={id}` lists the same children as a flat list.

Setting or clearing `parent_id` through PATCH writes one `field_change` entry, for example
`sunny-crane changed parent_id from (none) to 3`. Setting the parent a ticket already has is
a no-op. Nothing is rolled up: a parent's `status`, `priority` and `needs_human_eyes` are its
own, and the sidebar badge counts flagged tickets one by one, parents and sub-tickets alike.

```bash
curl -s -X POST http://localhost:8000/api/tickets -H 'Content-Type: application/json' \
  -d '{"title":"Write the migration","parent_id":3,"actor_session_id":"human"}'

curl -s 'http://localhost:8000/api/tickets?parent=3'
```

Four requests are rejected with `400`, after the actor and ticket checks:

| Body | When |
|---|---|
| `{"detail": "unknown parent"}` | No ticket has that `parent_id`. |
| `{"detail": "a ticket cannot be its own parent"}` | `parent_id` is the ticket's own id. |
| `{"detail": "a sub-ticket cannot have sub-tickets"}` | The requested parent already has a parent. |
| `{"detail": "a ticket with sub-tickets cannot become one"}` | The ticket being patched already has children. |

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

Add a comment. Body: `body` (required, non-empty after stripping surrounding
whitespace), `actor_session_id` (required). The body is otherwise stored verbatim.

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

#### `GET /api/tickets/{id}/brief`

The HTML brief a `ticket_brief` session wrote for this ticket, served as
`text/html; charset=utf-8` with the file's bytes as the body. This is the only endpoint
that answers with a document instead of JSON, so it is deliberately left out of the
OpenAPI document (`include_in_schema=False`) and out of the generated frontend client,
which describe the JSON contract alone. The ticket page links to it; open it in a browser.

`404` when the ticket has no brief, and also when the row points at a file that is no
longer there — `BRIEFS_DIR` is an ordinary directory that can be emptied, and a brief with
no document behind it is the same to a reader as never having been briefed.

```bash
curl -s http://localhost:8000/api/tickets/1/brief -o brief.html
```

### Tasks

A task is one small piece of a ticket's work: "write the migration", "expose the endpoint".
A ticket has any number of tasks; a task belongs to exactly one ticket and is deleted with
it. Tasks are not tickets: they have no status, priority, tags or flag, only a `state`.

Two response shapes. `Task` is what `TicketDetail.tasks` and `GET /api/tickets/{id}/tasks`
carry:

```
id, ticket_id, title, description, state, depends_on, blocked_by, created_at, updated_at
```

`TaskDetail` is `Task` plus `history`, and is what every task mutation returns. Each history
entry has the same flat shape as a timeline entry, with states instead of statuses:

```
id, kind, actor {session_id, name, directory}, body, created_at, from_state, to_state, reason
```

`kind` is `state_change` or `field_change`; fields that do not apply are `null`. `state` is
one of `todo` (default), `in_progress`, `done`, `cancelled`.

**Dependencies.** `depends_on` is the list of task ids this task waits on, always sorted and
de-duplicated. `blocked_by` is the subset of `depends_on` whose state is not `done` or
`cancelled`; a `todo` task with an empty `blocked_by` is ready to start. Dependencies are
advisory: the server does not stop you finishing a task whose dependencies are still open.
What it does enforce is that the tasks on a ticket form a DAG:

| Body | When |
|---|---|
| `{"detail": "unknown dependency"}` | An id in `depends_on` is not a task on this ticket (including a task on another ticket). |
| `{"detail": "a task cannot depend on itself"}` | `depends_on` contains the task's own id. |
| `{"detail": "dependencies would form a cycle"}` | Some task in `depends_on` already depends, directly or through others, on this task. |

All three are `400`, checked after the actor check. `PATCH` replaces the whole list, so to
reverse an edge `b -> a` into `a -> b`, clear `b` first and then point `a` at `b`.

Every task mutation bumps the ticket's `updated_at` (A8: task activity is ticket activity)
but writes nothing to the ticket's `timeline`; the record lives in the task's `history`.

#### `POST /api/tickets/{id}/tasks`

Create a task on the ticket. Body: `title` (required, stripped, non-empty), `description`
(default `""`), `depends_on` (default `[]`), `actor_session_id` (required). Returns `201` with
`TaskDetail`. The state cannot be set here; use the state endpoint.

```bash
curl -s -X POST http://localhost:8000/api/tickets/1/tasks -H 'Content-Type: application/json' \
  -d '{"title":"Write the migration","actor_session_id":"0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f"}'

curl -s -X POST http://localhost:8000/api/tickets/1/tasks -H 'Content-Type: application/json' \
  -d '{"title":"Expose the endpoint","depends_on":[1],"actor_session_id":"0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f"}'
```

```json
{
  "id": 2,
  "ticket_id": 1,
  "title": "Expose the endpoint",
  "description": "",
  "state": "todo",
  "depends_on": [1],
  "blocked_by": [1],
  "created_at": "2026-09-16T03:10:12.418Z",
  "updated_at": "2026-09-16T03:10:12.418Z",
  "history": []
}
```

#### `GET /api/tickets/{id}/tasks`

The ticket's tasks as `Task[]`, oldest first. The same rows as `TicketDetail.tasks`. Unknown
ticket returns `404`.

#### `GET /api/tasks/{task_id}`

One task as `TaskDetail`. Unknown id returns `404`.

#### `PATCH /api/tasks/{task_id}`

Edit fields. Body: any of `title`, `description`, `depends_on`, plus `actor_session_id`
(required). Same rules as the ticket PATCH: per-key replace, omitted keys untouched,
`depends_on` replaces the whole list (`[]` clears it). No task field is nullable, so `null`
on any of them is `422`. One `field_change` history entry is written per field that actually
changed, with the ticket's body copy (`<name> changed depends_on from 1 to 1, 3`,
`<name> changed description`). A PATCH that changes nothing writes nothing.

```bash
curl -s -X PATCH http://localhost:8000/api/tasks/2 -H 'Content-Type: application/json' \
  -d '{"depends_on":[1,3],"actor_session_id":"human"}'
```

#### `POST /api/tasks/{task_id}/state`

Set the state. Body: `state` (one of the four names; anything else is `422`), `reason`
(optional; blank becomes `null`), `actor_session_id` (required). Writes a `state_change`
entry with body `<name> changed state from <old> to <new>`. Setting the state a task already
has returns `200` and writes nothing.

```bash
curl -s -X POST http://localhost:8000/api/tasks/1/state -H 'Content-Type: application/json' \
  -d '{"state":"done","reason":"Migration applied on staging","actor_session_id":"0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f"}'
```

```json
{
  "id": 1,
  "ticket_id": 1,
  "title": "Write the migration",
  "state": "done",
  "depends_on": [],
  "blocked_by": [],
  "history": [
    {
      "id": 1,
      "kind": "state_change",
      "actor": { "session_id": "0f2c7e1a-3b4d-4c5e-9f60-7a8b9c0d1e2f", "name": "sunny-crane", "directory": "/home/me/code/avantos" },
      "body": "sunny-crane changed state from todo to done",
      "created_at": "2026-09-16T03:12:40.902Z",
      "from_state": "todo",
      "to_state": "done",
      "reason": "Migration applied on staging"
    }
  ],
  "...": "..."
}
```

After this, `GET /api/tasks/2` shows `"blocked_by": []` while `depends_on` still lists `1`.

The detail page lists a ticket's tasks under "Tasks" with a state chip, a `blocked` badge, and
a per-task state select. Clicking a task's title shows its history. The "New task" form takes
a title and, once the ticket has tasks, a multi-select of dependencies.

### Crons

One `CronRun` row is one pass (see "Crons"). The `CronRun` shape:

```
id, status, trigger, summary, error, pid, started_at, created_at, finished_at
```

`status` is `running`, `finished`, or `failed`. `trigger` is `api` or `command`. `summary`
and `error` are `""` until there is something to say; `pid` is the detached worker's
process id, `null` for a run started by the command in the foreground. `finished_at` is
`null` while the run is in flight.

#### `POST /api/crons/run`

Start a pass. No body. Returns `202` with a `CronRun` that is already `running` and whose
worker has been started, or `200` with the run already in flight when there is one. The
`200` is not an error: the caller joins that run, and no second worker is launched.

```bash
curl -s -X POST http://localhost:8000/api/crons/run
```

```json
{
  "id": 1,
  "status": "running",
  "trigger": "api",
  "summary": "",
  "error": "",
  "pid": 48213,
  "started_at": "2026-09-17T09:15:00.412Z",
  "created_at": "2026-09-17T09:15:00.412Z",
  "finished_at": null
}
```

A second call while that run is in flight answers `200` with the same row. Once the worker
is done the run reads:

```json
{
  "id": 1,
  "status": "finished",
  "summary": "2 tickets, 1 brief, 3 pull requests, 1 triage",
  "finished_at": "2026-09-17T09:18:44.905Z",
  "...": "..."
}
```

#### `GET /api/crons/summary`

Whether a pass is running, and the latest run whatever its state. The header reads this.

```bash
curl -s http://localhost:8000/api/crons/summary
```

```json
{
  "running": false,
  "last_run": {
    "id": 1,
    "status": "finished",
    "trigger": "api",
    "summary": "2 tickets, 1 brief, 3 pull requests, 1 triage",
    "error": "",
    "pid": 48213,
    "started_at": "2026-09-17T09:15:00.412Z",
    "created_at": "2026-09-17T09:15:00.412Z",
    "finished_at": "2026-09-17T09:18:44.905Z"
  }
}
```

`last_run` is `null` before the first run.

#### `GET /api/crons/runs`

Every run as `CronRun[]`, newest first.

#### `GET /api/crons/runs/{id}`

One run as `CronRun`. Unknown id returns `404`.

### Alerts

An alert is something that happened while nobody was watching and wants a person to look
at it. The `Alert` shape:

```
id, kind, message, ticket, session, pull_request, cron_run_id, dismissed_at, created_at
```

`kind` is one of:

| Kind | Raised when |
|---|---|
| `new_ticket` | The import created a ticket from a Linear issue. |
| `pr_triaged` | A triage session judged a PR's comments; its ticket is now blocked and flagged. |
| `pr_unlinked` | A PR names no ticket this app knows. Raised once, not again until it is dismissed. |
| `cron_error` | A step was skipped for missing config, a step raised, a spawned session failed, or a run was abandoned by its worker. |

Every link is nullable, because an alert is about the event and not about any one row.
`ticket` is `{id, title}`; `pull_request` is `{id, number}`; `session` is the full `Actor`
(`{session_id, name, directory}`), so the alerts page can offer to resume the transcript
that produced the alert.

#### `GET /api/alerts`

Alerts newest first. By default only the undismissed ones — the page is a to-do list.
`?dismissed=true` returns the whole history instead, dismissed rows included. Nothing is
ever deleted.

```bash
curl -s http://localhost:8000/api/alerts
curl -s 'http://localhost:8000/api/alerts?dismissed=true'
```

```json
[
  {
    "id": 4,
    "kind": "pr_triaged",
    "message": "PR #123 triaged: 3 comments judged, waiting on a human review",
    "ticket": { "id": 1, "title": "Fix login redirect" },
    "session": {
      "session_id": "3a7f1d02-9c44-4a11-b0e6-2d5c8f31aa90",
      "name": "neat-finch",
      "directory": "/home/me/code/avantos"
    },
    "pull_request": { "id": 2, "number": 123 },
    "cron_run_id": 1,
    "dismissed_at": null,
    "created_at": "2026-09-17T09:18:41.377Z"
  },
  {
    "id": 3,
    "kind": "cron_error",
    "message": "Skipped write ticket briefs: set BRIEFS_DIR.",
    "ticket": null,
    "session": null,
    "pull_request": null,
    "cron_run_id": 1,
    "dismissed_at": null,
    "created_at": "2026-09-17T09:15:02.008Z"
  }
]
```

#### `GET /api/alerts/summary`

How many alerts are still undismissed — the same rows the default list shows. The sidebar
badge reads this.

```bash
curl -s http://localhost:8000/api/alerts/summary
```

```json
{ "undismissed_count": 2 }
```

#### `POST /api/alerts/{id}/dismiss`

Mark an alert handled. No body. Returns `200` with the `Alert`. Dismissing an alert that is
already dismissed is a no-op: still `200`, and `dismissed_at` keeps the moment the first
call wrote, so the history does not lie about when the work was done. Unknown id returns
`404`.

```bash
curl -s -X POST http://localhost:8000/api/alerts/4/dismiss
```

### Pull requests

A `PullRequest` row is a cache of what GitHub last said, keyed by the identity GitHub
itself uses, `(repo, number)`. The `PullRequestItem` shape:

```
id, repo, number, url, title, branch, head_sha, state, author, ticket_id, comment_count,
last_triage_session
```

`state` is lower-cased on the way in (`open`, `merged`, `closed`), so it reads like every
other state in this API. `ticket_id` is `null` until the cron or a human links the PR.
`comment_count` is how much has been said across GitHub's three comment feeds.
`last_triage_session` is the full `Actor` of the session that last triaged the comments, or
`null`, so the row can name it and offer to resume it.

#### `GET /api/pull-requests`

Every PR as `PullRequestItem[]`, grouped by repo, highest number first.

```bash
curl -s http://localhost:8000/api/pull-requests
```

```json
[
  {
    "id": 2,
    "repo": "mosaic-avantos/avantos",
    "number": 123,
    "url": "https://github.com/mosaic-avantos/avantos/pull/123",
    "title": "[CON-7] Keep the task id on handoff dispatch",
    "branch": "brendonkeirle/con-7-handoff",
    "head_sha": "9f1c2ae6d3b74c0f8ab21d5e7c4a90b3d6e81f42",
    "state": "open",
    "author": "Brendonk13",
    "ticket_id": 1,
    "comment_count": 6,
    "last_triage_session": {
      "session_id": "3a7f1d02-9c44-4a11-b0e6-2d5c8f31aa90",
      "name": "neat-finch",
      "directory": "/home/me/code/avantos"
    }
  }
]
```

#### `GET /api/pull-requests/{id}`

One PR as `PullRequestItem`. Unknown id returns `404`.

#### `PATCH /api/pull-requests/{id}`

Say which ticket a PR is work on, when the identifier match could not. Body: `ticket_id`
(required) and `actor_session_id` (required). Returns `200` with the `PullRequestItem`.

The match only fires when a branch, title, or body names a ticket this app already holds,
so a branch cut before its ticket existed arrives unlinked and stays that way until
somebody finishes the job here. Linking writes one `field_change` entry on the ticket's
timeline — the same entry the cron writes, only with your actor on it. Asking for the link
the PR already has writes nothing.

Checks run `404` (no such PR) → `400` (unknown actor) → `400 {"detail": "unknown ticket"}`.

```bash
curl -s -X PATCH http://localhost:8000/api/pull-requests/2 -H 'Content-Type: application/json' \
  -d '{"ticket_id":1,"actor_session_id":"human"}'
```

### Errors

| Code | When | Body |
|---|---|---|
| `422` | Body fails validation (missing field; empty or whitespace-only `title`/`reason`/`body`/`status`; `status` over 100 chars; `null` on a non-nullable PATCH field; bad `priority`, `state`, `sort`, or `order`). | `{"detail": [ ...pydantic errors... ]}` (a list) |
| `422` | `PUT /api/sessions/{id}` with a reserved id: `human` or `cron`. No session may claim either name. | `{"detail": "session_id 'cron' is reserved"}` (a string) |
| `404` | Ticket id does not exist. | `{"detail": "Not Found: No Ticket matches the given query."}` (`DEBUG=True` form) |
| `404` | Task id does not exist. | `{"detail": "Not Found: No Task matches the given query."}` (`DEBUG=True` form) |
| `404` | Cron run, alert, or pull request id does not exist. | `{"detail": "Not Found: No CronRun matches the given query."}` (`DEBUG=True` form) |
| `404` | The ticket has no brief. | `{"detail": "Not Found: No TicketBrief matches the given query."}` (`DEBUG=True` form) |
| `404` | The ticket has a brief but the file it points at cannot be read. | `{"detail": "no brief for this ticket"}` |
| `400` | `actor_session_id` is not a registered session and not `human` or `cron`. | `{"detail": "unknown actor"}` |
| `400` | `ticket_id` on `PATCH /api/pull-requests/{id}` names no ticket. | `{"detail": "unknown ticket"}` |
| `400` | `parent_id` names no ticket, or breaks the one-level rule (see "Sub-tickets"). | `{"detail": "unknown parent"}` and three others |
| `400` | `depends_on` names a task off this ticket, the task itself, or would close a cycle (see "Tasks"). | `{"detail": "unknown dependency"}` and two others |

The checks run in that order, so a bad body on a missing ticket is `422`, and an unknown
actor on a missing ticket is `404`.

## Project layout

```
task-tracking/
  Makefile                      # install, dev, test, gen-api, check-contract, e2e
  PLAN.md                       # the TDD build plan
  docs/ARCHITECT_MEMO.md        # binding amendments A1-A26 to the plan
  .github/workflows/ci.yml      # backend, frontend, contract, e2e jobs
  backend/                      # Django 6 + django-ninja + SQLite, managed by uv
    manage.py
    .env.example                # copy to .env; every cron setting lives here
    var/                        # gitignored: worker logs, triage analyses (CRON_WORK_DIR)
    config/settings.py, urls.py # api mounted at /api
    tracker/
      models.py                 # Ticket, Tag, Status, Session, TimelineEntry, Task, TaskDependency,
                                # TaskHistoryEntry, CronRun, Alert, TicketBrief, PullRequest, PRComment
      schemas.py                # request/response schemas (the OpenAPI source of truth)
      api/tickets.py, sessions.py, statuses.py, tasks.py, crons.py, alerts.py, pull_requests.py
      services/actors.py, tags.py, names.py, tasks.py (DAG checks), changes.py,
        tickets.py, sessions.py, crons.py, briefs.py, pull_requests.py, triage.py
      integrations/             # the wire: linear.py, github.py, claude_runner.py, processes.py
      management/commands/run_cron.py
      migrations/               # 0007 seeds the ten built-in statuses; 0016 adds the cron models
      tests/                    # pytest, HTTP through ninja's TestClient
  frontend/                     # Vite + React 19 + TypeScript + Tailwind + shadcn, managed by pnpm
    openapi.json                # exported from the backend by make gen-api (gitignored)
    e2e/                        # Playwright smoke test
    src/
      api/schema.d.ts           # GENERATED from openapi.json, never hand-edited
      api/client.ts             # openapi-fetch client typed by schema.d.ts
      api/hooks/                # react-query hooks, one file per resource
      components/layout/        # AppShell, Sidebar (badges from /api/tickets/summary and /api/alerts/summary)
      components/tickets/       # TicketBadges, StatusFilter, TaskList, PullRequestList
      components/crons/         # RunCronsButton
      components/sessions/      # ResumeSessionButton
      pages/                    # TicketListPage, TicketDetailPage, SessionsPage, AlertsPage
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
