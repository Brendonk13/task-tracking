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
