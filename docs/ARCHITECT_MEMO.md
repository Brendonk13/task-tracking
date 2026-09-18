# Architect memo — PLAN.md sections 1–3 (task 0.1)

Produced by the Architect agent on 2026-09-12. Findings from lookups that shape the memo:

- django-ninja: `List[str]` query params use `QueryDict.getlist`, so `?status=a&status=b` works natively; its `TestClient(api)` bypasses the URL resolver, so test paths are relative to the API root (`/tickets`, not `/api/tickets`).
- Ninja 1.x is on pydantic v2, which renders aware UTC datetimes with a `Z` suffix.
- `openapi-typescript` 7.x has peer `typescript ^5.x` (pin TS 5). `openapi-fetch` 0.17 default array serialization is `form, explode: true`, yielding repeated `status=` params, which is what B4.4/F2.3 need.
- The plan's `cool-willow set status to planning` is asserted as an exact string in B3.4/B3.5, but a Test Writer cannot know which name a seeded RNG will produce before the generator exists. That is the largest hidden conflict.

## Confirmed

- Domain language in section 1 is consistent and sufficient; keep `medium` (not `med`) as the enum spelling.
- Single nullable current status; status/flag/comment/patch are the only mutations; timeline is one append-only table; `needs_human_eyes` is explicit, not derived.
- `labels` in every response are **de-duplicated and sorted alphabetically** (B2.4). `project` is a single string or `null`.
- Tag uniqueness is on `(kind, name)`, so `"avantos"` may exist as both a project and a label.
- Priority rank for `sort=priority`: `urgent=4, high=3, medium=2, low=1, none=0`. `order=desc` yields urgent first (B2.7).
- Default list ordering: `sort=created_at`, `order=desc` (B2.6).
- Timestamps everywhere are ISO 8601 UTC with `Z` (Django `USE_TZ=True`, `TIME_ZONE="UTC"`). Ticket has `created_at`, `updated_at`; timeline entries and sessions have `created_at`.
- Timeline detail order: `created_at asc`, ties by `id asc`.
- Status-change no-op: same status → 200, no entry, `updated_at` untouched (B3.7).
- Status filter is exact-match OR across repeated `status=` params. Unknown status name in a filter returns an empty list (200), never 404/422.
- Error contract as written: `400 {"detail": "unknown actor"}`, `404` for unknown ticket, ninja default `422` (`detail` is a *list* there, not a string).
- Seams (section 3) are correct. Only two stubs are allowed: clock (`freezegun`) and the name generator RNG.
- Frontend stack: `openapi-typescript@^7` with `openapi-fetch@^0.17`; default `querySerializer` produces repeated `status=` params, satisfying F2.3.

## Amendments

**A1 — Actor sub-schema and the `human` actor.** (Section 1 "Actor", B3.10, F3.4, F3.5)
`Actor` (response sub-schema on every timeline entry): `{session_id: string, name: string, directory: string | null}`. For a registered session, values are read live from the Session row (not snapshotted). For the reserved literal the actor is exactly `{"session_id": "human", "name": "human", "directory": null}` and body copy uses `human` as the name, e.g. `human set status to planning`. F3.5: the resume button is not rendered when `actor.directory` is null.

**A2 — Response schema names.** (Section 2, B4.6, Contract Sync)
Response schemas (these names become `components.schemas` keys in `schema.d.ts`): `Session`, `TicketListItem`, `TicketDetail`, `TimelineEntry`, `Actor`, `StatusItem`, `TicketsSummary`. Request schemas: `SessionIn`, `TicketCreate`, `TicketPatch`, `StatusChangeIn`, `CommentIn`, `NeedsHumanEyesIn`. `TicketListItem` = `{id, title, priority, status, needs_human_eyes, project, labels, linear_url, created_at, updated_at}`. `TicketDetail` = `TicketListItem` + `description` + `timeline: TimelineEntry[]`. `TimelineEntry` = `{id, kind, actor: Actor, body, created_at, from_status, to_status, reason}` — one flat schema; inapplicable fields are `null` (no discriminated union).

**A3 — Status codes and return bodies.** (Section 2 API table)
`POST /api/tickets` → 201 `TicketDetail`. `PATCH`, `POST .../status`, `.../comments`, `.../needs-human-eyes` → 200 `TicketDetail` (also on no-op). `PUT /api/sessions/{id}` → 200 `Session` on both first and later calls. `GET /api/tickets` → 200 `TicketListItem[]` (plain array, no envelope). Order of checks on mutating ticket endpoints: 422 validation → 404 ticket → 400 actor. `status` and `needs_human_eyes` are not settable on `POST /api/tickets`.

**A4 — PATCH semantics.** (B2.5)
Per-key replace, omitted keys untouched (`exclude_unset`). `labels` replaces the whole set (`[]` clears). `project: null` and `linear_url: null` clear. `description` is a non-null string, default `""`. Writes **one `field_change` entry per field whose value actually changed**; a PATCH that changes nothing returns 200 and writes nothing.

**A5 — `field_change` body copy.** (B2.5)
Body is `<name> changed <field> from <old> to <new>` where `null`/empty renders as `(none)`, lists render comma-joined sorted (`ai, infra`), other values verbatim. Exception: `description` writes `<name> changed description` with no values. Fields are the JSON key names. `from_status`/`to_status`/`reason` are `null` on `field_change`.

**A6 — `flag_change` copy and no-op.** (B4.1)
Body is `<name> flagged needs human eyes` or `<name> cleared needs human eyes`; `reason` optional, stored on the entry (`null` if absent). Setting the flag to its current value is a no-op: 200, no entry.

**A7 — `reason` requiredness.** (B3.3, B4.1)
`reason` is required (non-empty) on `POST .../status`; optional on `.../needs-human-eyes`. Comment `body` is required non-empty. Status names are stripped of surrounding whitespace, must be non-empty, are case-sensitive and stored verbatim.

**A8 — `updated_at` semantics.**
`updated_at` bumps on every non-no-op mutation, including comments, so `sort=updated_at` means "recent activity".

**A9 — List tie-breaks.** (B2.6, B2.7)
Ties are broken by `created_at` then `id`, both following `order`.

**A10 — Session nullable fields and PUT merge rule.** (B1.1, B1.2, B1.4)
`Session` = `{session_id, name, directory, last_message: string | null, last_message_at: datetime | null, created_at}`. `directory` is required on every PUT. `last_message`/`last_message_at` omitted → **kept**; explicit `null` → cleared. `last_message_at` accepts any ISO 8601 datetime; naive values are treated as UTC; response returns UTC `Z`. `GET /api/sessions` orders `last_message_at desc` with nulls last, then `created_at desc`.

**A11 — `cool-willow` is illustrative; tests read the name back.** (B3.4, B3.5, B3.8, B3.10, section 3)
The test registers a session first and takes `name` from the PUT response, then asserts `body == f"{name} set status to planning"`. RNG seeding is only needed for B1.3 determinism, via `tracker.services.names.generate_name(rng)` where conftest swaps the module-level `Random`.

**A12 — Test paths are relative to the API root.** (Section 3, conftest)
`conftest.py` exposes `client = ninja.testing.TestClient(api)`. Tests call `client.get("/tickets")`, not `/api/tickets`. All test modules use `pytest.mark.django_db`.

**A13 — Statuses module and list order.** (B3.1, B3.6)
Add `tracker/api/statuses.py`. `GET /api/statuses` returns `StatusItem[]` = `{name, is_builtin}`; built-ins first in the canonical order of section 1, then customs sorted by name. B3.1 may assert exact list equality.

**A14 — Route registration order.** (B4.5)
Ticket `id` is an integer. Register `GET /tickets/summary` before `GET /tickets/{id}`.

**A15 — Contract generation without a running server.** (0.3, 0.4, 8.2)
`make gen-api` runs `uv run python manage.py export_openapi_schema --api tracker.api.api --output ../frontend/openapi.json` then `pnpm gen:api` (`openapi-typescript openapi.json -o src/api/schema.d.ts`). `check-contract` regenerates and `git diff --exit-code src/api/schema.d.ts`. No server needed.

**A16 — Frontend client base URL and dev proxy.** (0.3, `api/client.ts`, `test/msw.ts`)
`createClient<paths>({ baseUrl: window.location.origin })`. Vite `server.proxy: { "/api": "http://localhost:8000" }`. MSW handlers use relative paths (`http.get("/api/tickets", ...)`). Node fetch rejects relative URLs, so a relative `baseUrl` would break Vitest.

## Amendments — crons (A17+)

**A17 — The reserved actor `cron`.** (Crons §1, C1.10)
`cron` joins `human` as a reserved literal in `actors.RESERVED_ACTORS`, resolving to `{"session_id": "cron", "name": "cron", "directory": null}`. It is the actor for writes the backend makes on its own behalf, where there is no session and no person: importing a ticket, linking a PR to a ticket. It is accepted by `require_actor` like `human`, and `PUT /api/sessions/cron` is rejected `422` like `PUT /api/sessions/human` — a reserved name must never resolve to a Session row, or the actor a timeline entry names could be quietly reassigned. A write derived from a session's output is attributed to that session, not to `cron` (A24).

**A18 — New response schema names.** (A2, Contract Sync)
New response schemas (`components.schemas` keys in `schema.d.ts`): `CronRun`, `CronsSummary`, `Alert`, `AlertsSummary`, `PullRequestItem`, `PullRequestRef`, `TicketBrief`, `TicketPullRequest`. New request schema: `PullRequestPatch` (`{ticket_id, actor_session_id}`). `Session` gains `purpose`, `model`, `effort`, `status`, `result_summary`, `finished_at`; `TicketListItem` gains `linear_identifier`; `TicketDetail` gains `brief: TicketBrief | null` and `pull_requests: TicketPullRequest[]`. `Alert.ticket` is a `TicketRef` and `Alert.pull_request` a `PullRequestRef` rather than bare ids, because the page renders links and a bare id names nothing a person recognises; `Alert.session` and `PullRequestItem.last_triage_session` are the full `Actor` (A1), because a resume button needs `directory`.

**A19 — `POST /api/crons/run` answers 202 or 200.** (C5.1, C5.2)
202 with a `CronRun` in `status running` when this call started the pass and spawned the worker; 200 with the run already in flight when one was. A caller arriving mid-run is not in error, so it joins that run rather than being refused, and 202 keeps its plain meaning: "I started one, follow it at `GET /crons/summary`". The view's check is an optimisation, not the guarantee — the `one_running_cron_run` partial unique constraint is, so two callers racing never both insert. The loser asks again rather than assuming: it joins the winner's run with 200 if that run is still in flight, and starts the pass it was asked for if the winner has already finished, because a caller cannot follow a run that is over.

**A20 — Dismissing an alert is idempotent.** (C5.6, A6 no-op rule)
`POST /api/alerts/{id}/dismiss` returns 200 with the `Alert` whether or not it was already dismissed, and a second call leaves `dismissed_at` at the moment the first one wrote. Re-stamping it would make the history claim the work was done later than it was. Unknown id is 404. `GET /api/alerts` hides dismissed rows unless `?dismissed=true`; nothing is ever deleted.

**A21 — The brief endpoint is not part of the JSON contract.** (C2.4, A15)
`GET /api/tickets/{id}/brief` answers `text/html; charset=utf-8` with the bytes of the file, and is registered `include_in_schema=False`. It is a document a person opens, not data a client parses, so describing it in OpenAPI would put a non-JSON route into the generated frontend client and into `schema.d.ts` where every other entry is a JSON contract. The frontend links to the path directly. The row can outlive the file, since `BRIEFS_DIR` is an ordinary directory, so an unreadable `html_path` is 404 — a missing document reads the same as never having been briefed.

**A22 — Identity of the cached GitHub rows.** (C3.4, C3.5)
`PullRequest` is unique on `(repo, number)`; `PRComment` is unique on `(pull_request, kind, github_id)`. Both rows are caches of something this app can only read, so they are keyed by what GitHub itself calls them, and every pass upserts on that key. `kind` is part of a comment's identity because GitHub's three feeds number their items separately, so the same id can name an inline comment and a review. This is what makes a pass idempotent: re-reading a feed every fifteen minutes recognises what it already holds instead of doubling the conversation. `triaged_by`/`triaged_at` are the only columns this app writes on those rows itself.

**A23 — The Linear-identifier match.** (C1.7, C3.2)
Identifiers are normalised to uppercase at the one place they are read (`identifiers_in`), because GitHub lower-cases them in a branch name (`con-2513`) and shouts them in a title (`[CON-2386]`); nothing else compares case. A PR is matched against branch, then title, then body — the branch is the one place the identifier was chosen deliberately. A match is only ever accepted when it names a ticket this app already holds, keyed by `linear_identifier` or by the identifier in a hand-pasted `linear_url`. So a string that merely looks like a key (`utf-8`) links nothing, and a branch cut before its ticket existed arrives unlinked, raises `pr_unlinked` and waits for `PATCH /api/pull-requests/{id}`. Guessing a ticket is worse than leaving the PR unplaced: a wrong link writes tasks and a block onto somebody else's work.

**A24 — Triage writes are attributed to the triage session.** (C4.5, C4.7)
The status change, the flag, and every task history entry a triage produces carry the triage session's `session_id`, not `cron`. The transcript is the only place the judgement can be checked, and `Actor.directory` on a session is what lets the UI offer `claude --resume`. `cron` is reserved for writes no session made (A17). The `pr_triaged` alert carries all three of `ticket`, `pull_request` and `session`, because it is the one signal that reaches a person not already on the ticket.

**A25 — The worker execution model.** (C5.1, C5.3)
`POST /api/crons/run` records the run and returns; the work is done by `manage.py run_cron <id>` started through `processes.popen` with `start_new_session=True`, under `sys.executable`, with stdout and stderr appended to `<CRON_WORK_DIR>/crons/run-<id>.log`. `runserver` autoreloads, so a pass inside the web process would be killed half-finished on the next file save, and a pass takes minutes, which is longer than a request may be held. The worker is handed the id of the recorded run so it does *that* run; a worker starting one of its own would leave the recorded row `running` for ever and the frontend would follow a run nobody was doing. The pid is stored so a later trigger can tell a live run from a dead one: `reap_stale` asks `processes.pid_alive` first and fails any run whose worker is gone, with a `cron_error` naming it. A run with no pid is never reaped — nothing was started for it to lose.

**A26 — The two new seams.** (Crons §3, S2 and S3)
S2: tests drive cron logic only through `call_command("run_cron", ...)`, never by importing `services/crons.py` functions. The command is the entry point both the API and a scheduler use, so a test that goes round it tests something nobody runs. S3: the wire is faked, not our code. Every external process goes through the three module-level attributes in `tracker/integrations/processes.py` (`run`, `popen`, `pid_alive`), and Linear goes through `LinearClient(..., transport=...)`; those are the only objects `monkeypatch` may swap. Production code must call them as attributes (`processes.run(...)`), never import the names, or the swap is not seen. Our argv building, prompt text, allow/deny lists and parsing therefore run for real in every test. Asserting on recorded argv is asserting on behaviour at the boundary and is allowed; asserting call counts on our own modules is not. The sanctioned stubs are now exactly: clock, name RNG, `processes.run`/`popen`/`pid_alive`, Linear transport.
