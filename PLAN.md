# Task Tracking — TDD Build Plan for an Orchestrator

A personal, private ticket tracker whose main job is letting Claude Code sessions post
status changes and comments on tickets so a human can see what is blocked and what needs
their attention.

This document is written to be executed by an **orchestrator agent** that dispatches
sub-agents. Every feature is built as a sequence of **vertical slices**, each a strict
red → green cycle. No slice is started until the previous slice in its lane is green and
committed.

---

## 0. Ground rules for the orchestrator

### 0.1 The loop, per slice

1. **RED** — the *Test Writer* agent adds exactly one new test at a pre-agreed seam
   (section 3). It runs the suite. The new test must fail *for the intended reason*
   (missing behaviour, not a syntax error or import error in the test itself).
   Commit: `red(<lane>): <test name>`.
2. **VERIFY RED** — the orchestrator re-runs the suite itself and confirms: exactly the
   new test(s) fail, everything else still passes. If not, bounce back to step 1.
3. **GREEN** — the *Implementer* agent writes the *minimum* production code to pass. It
   may not edit the test file except to fix an objective error the orchestrator agrees
   with. Commit: `green(<lane>): <test name>`.
4. **VERIFY GREEN** — orchestrator re-runs the full suite (backend + frontend). All green.
5. Move to the next slice.

Refactoring is **not** part of the loop. It happens only in the *Review* step at the end
of each phase (section 5), and every refactor commit must leave the suite green.

### 0.2 Agent roster

| Agent | Type to launch | Responsibility | May edit |
|---|---|---|---|
| **Architect** | `Plan` (read-only) | Phase 0 only: confirm the domain model, API contract and seams below; flag conflicts. Output is a short markdown memo, not code. | nothing |
| **Test Writer** | `general-purpose` | Writes one failing test per slice at an agreed seam. Uses domain language from section 1. | `*/tests/**`, `*.test.tsx`, test fixtures/factories |
| **Implementer** | `general-purpose` | Makes the failing test pass with the smallest change. No speculative code, no extra endpoints, no "while I'm here". | production code, migrations, config |
| **Contract Sync** | `general-purpose` | After each backend phase: regenerate `frontend/src/api/schema.d.ts` from the live OpenAPI doc and commit. | `frontend/src/api/schema.d.ts` only |
| **Reviewer** | `code-review` skill / `general-purpose` | End of each phase. Checks the two axes: (a) tests are behavioural, not implementation-coupled or tautological; (b) code matches this plan. Proposes refactors as a list; Implementer applies them under a green suite. | nothing directly |
| **E2E** | `webapp-testing` skill | Phase 8 only: Playwright smoke test of the critical path against a real backend. | `e2e/**` |

Anti-cheat rules the orchestrator enforces:

- Test Writer and Implementer for the same slice are **different agent invocations**. The
  Implementer receives the failing test's output, not the Test Writer's reasoning.
- An Implementer that wants to change a test must stop and report; the orchestrator decides.
- A slice whose GREEN commit touches more than the slice needed is sent back to be trimmed.

### 0.3 Parallelism

- Backend lanes (B1–B4) are sequential within a lane and mostly sequential across lanes
  because they share `models.py`. Run them in the order given.
- Frontend lanes (F1–F4) can run **in parallel, one worktree per lane** (`isolation:
  "worktree"`), once the contract for that page is frozen (after Contract Sync for the
  backend phase it depends on). Merge order: F1 → F2 → F3 → F4.
- The orchestrator merges worktrees; it never lets two agents edit the same file at once.

### 0.4 Commands the orchestrator uses to verify

```bash
# backend
cd backend && uv run pytest -q
# frontend
cd frontend && pnpm test --run
cd frontend && pnpm typecheck
# contract drift (must be a no-op diff)
make gen-api && git diff --exit-code frontend/src/api/schema.d.ts   # see A15
# e2e (phase 8 only)
cd frontend && pnpm e2e
```

---

## 1. Domain language

Use these words everywhere: model names, test names, UI copy, API paths.

| Term | Meaning |
|---|---|
| **Ticket** | A unit of work. Has title, description, priority, optional `linear_url`, one optional **Project** tag, any number of **Label** tags, one current **Status** (nullable), and a `needs_human_eyes` flag. |
| **Priority** | Enum: `urgent`, `high`, `medium`, `low`, `none`. Default `none`. |
| **Tag** | A named string with a `kind` of `project` or `label`. A ticket has at most one project tag and any number of label tags. Tags are created on first use. |
| **Status** | A named string. Ten **built-in statuses** are seeded: `blocked`, `needs-help`, `planning`, `implementing-plan`, `diagnosing-ticket`, `needs-clarification`, `ready-for-pr`, `merged`, `tested-in-cloud`, `done`. Any other string is a **custom status**, created on first use. A ticket has **exactly one current status**, or none (`null`) before the first change. |
| **Session** | A Claude Code session registered with the app. Keyed by `session_id`. Stores `name` (generated, e.g. `cool-willow`), `directory`, `last_message`, `last_message_at`. |
| **Actor** | Who performed a ticket mutation. Every mutating ticket endpoint requires `actor_session_id`. It must match a registered Session, or be the reserved literal `human`. |
| **Timeline entry** | An append-only record on a ticket. `kind` is `comment` or `status_change` (or later `flag_change`, `field_change`). Always has `actor`, `created_at`, `body`. Status changes also carry `from_status`, `to_status`, `reason`. This is the "comments made by llms" feature and the "major events" feature in one list. |
| **Needs human eyes** | Boolean column on Ticket. Set explicitly through an endpoint. Drives the red badge in the sidebar. |
| **Resume command** | `cd <directory> && claude --resume <session_id>`. Built on the client from Session fields. |

Decisions made here so agents don't re-decide them:

- Timeline is **one table**, not separate comments and events tables. Rendering the detail
  page is a single ordered list.
- Status change **sets the single current status**: the request carries `status` and
  `reason`. The server records the previous status as `from_status` (may be `null`) and the
  new one as `to_status`, and the entry reads "changed status from X to Y" (or "set status to
  Y" when there was none). Setting the same status again is a no-op that returns 200 and
  writes nothing. New tickets start with `status: null`; the UI shows "no status".
- `needs_human_eyes` is **not** derived from statuses. It is set explicitly. (Auto-setting it
  from `blocked`/`needs-help`/`needs-clarification` is a candidate later slice, not now.)
- Session registration is **PUT, idempotent**: same `session_id` always updates in place;
  `name` is generated on first registration and never changes afterwards.
- No Linear API calls. `linear_url` is stored and linked, nothing is fetched.
- Human actions from the UI use `actor_session_id: "human"`.

---

## 2. Architecture and layout

```
task-tracking/
  backend/                      # Django + django-ninja + SQLite
    pyproject.toml              # uv; deps: django, django-ninja, pytest, pytest-django
    manage.py
    config/settings.py, urls.py # api mounted at /api ; openapi at /api/openapi.json
    tracker/
      models.py                 # Ticket, Tag, Status, Session, TimelineEntry
      schemas.py                # ninja Schemas (request/response)
      api/__init__.py           # NinjaAPI() + routers
      api/tickets.py
      api/sessions.py
      services/names.py         # adjective-animal name generator
      tests/
        conftest.py             # ninja TestClient fixture, factories
        test_tickets_api.py
        test_statuses_api.py
        test_timeline_api.py
        test_sessions_api.py
        test_flags_and_filters_api.py   # lane B4
  frontend/                     # Vite + React + TS + Tailwind + shadcn + react-query
    package.json                # pnpm; vitest, @testing-library/react, msw,
                                #   openapi-typescript, openapi-fetch, playwright
    src/
      api/schema.d.ts           # GENERATED — never hand-edited
      api/client.ts             # openapi-fetch client typed by schema.d.ts
      api/hooks/*.ts            # react-query hooks, one file per resource
      components/ui/*           # shadcn
      components/layout/Sidebar.tsx, AppShell.tsx
      pages/TicketListPage.tsx, TicketDetailPage.tsx, SessionsPage.tsx
      test/setup.ts, test/msw.ts   # MSW server, handlers built from fixtures
  e2e/                          # Playwright, phase 8
  PLAN.md
```

**Type flow:** django-ninja serves `/api/openapi.json` → `pnpm gen:api` runs
`openapi-typescript` → `schema.d.ts` → `openapi-fetch` client is fully typed → react-query
hooks wrap the client. A CI/orchestrator check fails if the committed `schema.d.ts` differs
from a fresh generation.

**API surface (the contract the Architect confirms in Phase 0):**

| Method | Path | Body / query | Notes |
|---|---|---|---|
| `PUT` | `/api/sessions/{session_id}` | `{directory, last_message?, last_message_at?}` | Idempotent upsert. Returns Session incl. generated `name`. |
| `GET` | `/api/sessions` | | List, newest `last_message_at` first. |
| `POST` | `/api/tickets` | `{title, description?, priority?, linear_url?, project?, labels?, actor_session_id}` | |
| `GET` | `/api/tickets` | `?status=blocked&status=needs-help&needs_human_eyes=true&sort=priority\|created_at\|updated_at&order=asc\|desc` | Status filter is OR across values. |
| `GET` | `/api/tickets/summary` | | `{needs_human_eyes_count}` for the sidebar badge. |
| `GET` | `/api/tickets/{id}` | | Ticket + `status` + `timeline[]` (oldest first). |
| `PATCH` | `/api/tickets/{id}` | `{title?, description?, priority?, project?, labels?, linear_url?, actor_session_id}` | Writes a `field_change` timeline entry. |
| `POST` | `/api/tickets/{id}/status` | `{status, reason, actor_session_id}` | Sets current status. Writes `status_change` with server-derived `from_status`. |
| `POST` | `/api/tickets/{id}/comments` | `{body, actor_session_id}` | Writes `comment`. |
| `POST` | `/api/tickets/{id}/needs-human-eyes` | `{value: bool, reason?, actor_session_id}` | Writes `flag_change`. |
| `GET` | `/api/statuses` | | Built-ins + customs seen so far, for filter UI. |

Error contract: unknown `actor_session_id` → `400 {"detail": "unknown actor"}`;
unknown ticket → `404`; validation → ninja's default `422`.

---

## 3. Seams under test (pre-agreed — no test is written anywhere else)

**Backend seam: HTTP through `ninja.testing.TestClient`.** Tests call endpoints and
assert on responses. They never query the ORM to verify; they verify by calling another
endpoint (e.g. POST then GET). SQLite test DB is real, not mocked. The only things
stubbed: the clock (`freezegun` or injected `now`) and the name generator's RNG (seeded).

**Frontend seam: page components rendered with React Testing Library, network replaced by
MSW handlers.** Tests interact as a user does (`getByRole`, `userEvent`) and assert on
what is on screen or what request MSW received. Hooks and the fetch client are never
tested directly. shadcn primitives are not tested.

**E2E seam (phase 8 only): Playwright against the real backend.** One flow.

Things we deliberately do **not** test: Django model methods in isolation, react-query
cache internals, the `openapi-fetch` client, Tailwind classes, sidebar animation.

---

## 4. Slices

Each row is one red → green cycle. "RED" is the test name the Test Writer must produce.
"GREEN scope" is the ceiling on what the Implementer may build.

### Phase 0 — Scaffold + Architect check (no TDD; infra only)

| # | Task | Agent | Done when |
|---|---|---|---|
| 0.1 | Architect reads this plan, produces `docs/ARCHITECT_MEMO.md` confirming or amending sections 1–3. Orchestrator applies amendments to this file before continuing. **Done: see section 9.** | Architect | memo committed |
| 0.2 | Backend scaffold: `uv init`, Django project, `tracker` app, ninja API mounted at `/api`, pytest-django configured, one trivial `test_openapi_is_served` that GETs `/api/openapi.json` and asserts 200. | Implementer | `uv run pytest` green |
| 0.3 | Frontend scaffold: Vite React-TS, Tailwind, shadcn init, react-query provider, react-router, Vitest + RTL + MSW wired, `pnpm gen:api` script (`openapi-typescript openapi.json -o src/api/schema.d.ts`, see A15), one smoke test rendering `<App/>`. | Implementer | `pnpm test --run` and `pnpm typecheck` green |
| 0.4 | Root `Makefile` or `justfile`: `dev` (both servers), `test`, `gen-api`, `check-contract`. | Implementer | commands work |

### Phase B1 — Sessions (backend)

Lane file: `tracker/tests/test_sessions_api.py`

| # | RED (test name) | GREEN scope |
|---|---|---|
| B1.1 | `test_register_session_returns_generated_name_and_stored_fields` — PUT with `directory`, `last_message`, `last_message_at`; response echoes fields and has a non-empty `name` matching `^[a-z]+-[a-z]+$`. | Session model + migration; PUT endpoint; name generator with seeded RNG hook. |
| B1.2 | `test_register_same_session_twice_keeps_name_and_updates_message` — two PUTs, second with new `last_message`; `name` unchanged, `last_message` updated, `GET /sessions` has exactly one row. | Upsert semantics; GET list. |
| B1.3 | `test_generated_names_are_unique_across_sessions` — register 50 sessions with a fixed seed; all names distinct. | Uniqueness retry loop in generator. |
| B1.4 | `test_list_sessions_orders_by_last_message_at_desc` | ordering |

### Phase B2 — Tickets core (backend)

Lane file: `tracker/tests/test_tickets_api.py`

| # | RED | GREEN scope |
|---|---|---|
| B2.1 | `test_create_ticket_then_get_returns_title_description_and_default_priority_none` — actor is a registered session. | Ticket model, POST, GET by id, actor validation helper. |
| B2.2 | `test_create_ticket_with_unknown_actor_is_rejected_with_400` | 400 path |
| B2.3 | `test_human_is_an_accepted_actor` — `actor_session_id: "human"` succeeds. | reserved literal |
| B2.4 | `test_create_ticket_with_project_and_labels_returns_them_as_tags` — `project: "avantos"`, `labels: ["infra","ai"]`; response has `project == "avantos"`, `labels == ["ai","infra"]` (sorted). | Tag model (kind), M2M, create-on-first-use |
| B2.5 | `test_patch_ticket_updates_fields_and_records_field_change_in_timeline` — PATCH priority to `urgent`; GET shows priority and a timeline entry of kind `field_change` whose `body` contains `"priority"` and actor `name`. | PATCH; TimelineEntry model; `timeline[]` in detail response |
| B2.6 | `test_list_tickets_returns_all_tickets_newest_first_by_default` | GET list |
| B2.7 | `test_list_tickets_sort_by_priority_puts_urgent_before_low` — create low, urgent, medium; `?sort=priority&order=desc` → `[urgent, medium, low]`. | priority rank ordering |
| B2.8 | `test_ticket_stores_linear_url` — create with `linear_url`; GET returns it. | field |

### Phase B3 — Statuses and timeline (backend) — **most important feature**

Lane files: `test_statuses_api.py`, `test_timeline_api.py`

| # | RED | GREEN scope |
|---|---|---|
| B3.1 | `test_built_in_statuses_are_listed` — `GET /statuses` returns the ten built-ins. | Status model, seed via data migration, GET |
| B3.2 | `test_new_ticket_has_no_status` — GET a fresh ticket → `status is None`. | nullable FK |
| B3.3 | `test_set_status_on_ticket_is_returned_as_current_status` — POST `{status:"planning", reason:"starting", actor}`; GET ticket → `status == "planning"`. | POST status endpoint |
| B3.4 | `test_first_status_writes_timeline_entry_set_status_with_actor_name_and_reason` — the test registers a session and reads `name` from the PUT response; body reads exactly `f"{name} set status to planning"` (A11); entry has `reason == "starting"`, `to_status == "planning"`, `from_status is None`. | status_change entry |
| B3.5 | `test_changing_status_writes_changed_from_to_entry` — set `planning`, then POST `{status:"implementing-plan", ...}`; `status == "implementing-plan"`; latest entry body `f"{name} changed status from planning to implementing-plan"`, `from_status == "planning"`. | server-derived from_status |
| B3.6 | `test_custom_status_is_created_on_first_use_and_then_listed` — `status:"waiting-on-vendor"`; `GET /statuses` now includes it with `is_builtin == false`. | custom statuses |
| B3.7 | `test_setting_same_status_again_writes_no_timeline_entry` — POST `planning` twice; 200 both times; exactly one `status_change` entry. | no-op path |
| B3.8 | `test_add_comment_appears_in_timeline_with_actor_name` — POST comments; timeline has kind `comment`, body verbatim, `actor.name`. | comments |
| B3.9 | `test_timeline_is_ordered_oldest_first_and_interleaves_comments_and_status_changes` — comment, status, comment with frozen clock stepping; assert the three kinds in order. | ordering |
| B3.10 | `test_timeline_actor_includes_session_id_directory_and_name` — so the UI can render the resume command per entry. | actor sub-schema |

### Phase B4 — Needs human eyes + filters (backend)

| # | RED | GREEN scope |
|---|---|---|
| B4.1 | `test_set_needs_human_eyes_true_is_reflected_on_ticket_and_timeline` — POST flag with reason; GET shows `needs_human_eyes == true` and a `flag_change` entry. | endpoint + column |
| B4.2 | `test_list_tickets_filter_needs_human_eyes_true_returns_only_flagged` | filter |
| B4.3 | `test_list_tickets_filter_by_single_status` — `?status=blocked` | filter |
| B4.4 | `test_list_tickets_filter_by_multiple_statuses_is_or` — `?status=blocked&status=needs-help` returns tickets with either. | multi-value |
| B4.5 | `test_summary_returns_count_of_tickets_needing_human_eyes` — three tickets, two flagged → `{needs_human_eyes_count: 2}`. | summary endpoint |
| B4.6 | `test_list_tickets_includes_status_and_needs_human_eyes_per_row` — list rows carry what the list page needs without N+1 detail calls. | list schema |

**→ Contract Sync after B4.** Commit `schema.d.ts`. Frontend lanes may now start.

### Phase F1 — App shell + sidebar (frontend)

Lane files: `src/components/layout/*.test.tsx`

| # | RED | GREEN scope |
|---|---|---|
| F1.1 | `renders sidebar with Tickets and Sessions links showing icon and label` | AppShell, Sidebar, two nav items, router |
| F1.2 | `collapsing the sidebar hides labels but keeps icons` — click toggle; `queryByText("Tickets")` null; icons still present via `aria-label`. | collapse state (persist to localStorage is optional, not tested) |
| F1.3 | `tickets nav item shows red badge with needs-human-eyes count from summary` — MSW `/api/tickets/summary` → `{needs_human_eyes_count: 3}`; badge text "3". | summary hook, badge |
| F1.4 | `badge is hidden when count is zero` | conditional |
| F1.5 | `home route renders the ticket list page` | routing |

### Phase F2 — Ticket list page (frontend)

| # | RED | GREEN scope |
|---|---|---|
| F2.1 | `lists tickets with title, priority and status chip, showing "no status" when null` — MSW returns 2 tickets, one with `status: null`. | list hook, table/cards |
| F2.2 | `filtering by status sends status query params and shows only returned tickets` — pick `blocked` in a status filter; assert MSW received `status=blocked`. | status filter UI using `/api/statuses` |
| F2.3 | `multiple statuses can be selected and are sent as repeated params` | multi-select |
| F2.4 | `needs-human-eyes toggle sends needs_human_eyes=true and renders alert styling on rows` | toggle + row styling |
| F2.5 | `sorting by priority sends sort=priority` | sort control |
| F2.6 | `clicking a ticket row navigates to its detail page` | link |
| F2.7 | `filters are reflected in the URL so a reload keeps them` | search params state |

### Phase F3 — Ticket detail page (frontend) — **most important page**

| # | RED | GREEN scope |
|---|---|---|
| F3.1 | `shows title, description, priority, current status, project tag and label tags` | detail hook, header |
| F3.2 | `renders timeline oldest first with comments and status changes styled differently` — fixture with one of each kind; status change rendered as an event line, comment as a bubble. | timeline list |
| F3.3 | `status change event reads "<name> changed status from X to Y" and shows the reason; first-ever change reads "<name> set status to Y"` | event copy + reason |
| F3.4 | `each timeline entry shows the actor session name` | actor display |
| F3.5 | `resume-session button on an entry copies "cd <dir> && claude --resume <id>" to clipboard` — stub `navigator.clipboard.writeText`. | resume button |
| F3.6 | `human can post a comment; request carries actor_session_id "human" and timeline refreshes` — MSW asserts body; refetch shows new entry. | comment form, mutation, invalidation |
| F3.7 | `human can change status via a select + reason field; request carries {status, reason, actor_session_id:"human"}` — select offers built-ins plus customs from /api/statuses and allows typing a new one. | status form |
| F3.8 | `human can toggle needs human eyes` | flag button |
| F3.9 | `linear url renders as an external link when present` | link |

### Phase F4 — Sessions page (frontend)

| # | RED | GREEN scope |
|---|---|---|
| F4.1 | `lists sessions with name, directory, last message and relative time` | sessions hook + table |
| F4.2 | `resume button copies the resume command for that session` | reuse F3.5 component |
| F4.3 | `sessions are ordered as returned by the API (newest activity first)` | no client re-sort |

### Phase 8 — E2E smoke + hardening

| # | Task |
|---|---|
| 8.1 | Playwright: register a session via API → create ticket via API → post a status change via API → open the UI → see the ticket in the list with status chip → open detail → see the event line with the session name → filter list by `blocked` → sidebar badge count matches. |
| 8.2 | Contract check in CI (`check-contract`). |
| 8.3 | `README.md`: how to run, how an LLM registers itself and posts (curl examples for each endpoint). |
| 8.4 | Reviewer full pass over both codebases. |

---

## 5. Review step (end of each phase)

The Reviewer answers, per phase:

1. Does every test assert on behaviour visible at the seam? Flag any that reach into the
   ORM, mock our own modules, or assert call counts.
2. Is any expected value computed the same way the code computes it? (Tautology check.)
3. Does the GREEN code contain anything no test demanded? List it for removal.
4. Duplication or naming drift from section 1? Propose refactors.

The orchestrator hands the list to an Implementer, who applies each item as its own
commit (`refactor(<lane>): ...`) with the suite green before and after.

---

## 6. Definition of done

- All slices green; `make test` and `make check-contract` pass from a clean clone.
- An LLM can, with only the README and curl: register itself, create a ticket, set its
  status with a reason, comment, and flag for human eyes. Posting with an unregistered
  `actor_session_id` is rejected with 400.
- Opening the app shows the ticket list, the sidebar badge count, filters by status and
  needs-human-eyes, and the detail page shows the interleaved timeline with
  "<name> changed status from X to Y" lines and working resume buttons.

## 7. Decisions confirmed by the owner (2026-09-12)

- Single current status per ticket, nullable, no default. Not a multi-status set.
- Unknown `actor_session_id` → 400. Sessions register first. `human` is reserved.
- Test Writer and Implementer are separate agent invocations on every slice.
- RTL + MSW tests for all four frontend pages, plus one Playwright smoke flow.
- Tickets are created via the API only. No create form. Linear URL stored, never fetched.

## 8. Explicitly out of scope (candidate later slices)

- Fetching title/description from Linear's API.
- Auto-setting `needs_human_eyes` from certain statuses.
- A "New ticket" form in the UI.
- Multiple simultaneous statuses per ticket (rejected on 2026-09-12; use `needs_human_eyes` or a custom status instead).
- Auth. The app is local and private.
- Real-time updates (polling via react-query `refetchInterval` is acceptable if wanted).
- Editing or deleting timeline entries. The timeline is append-only.

Follow-ups surfaced by the frontend reviews (2026-09-13), not blocking the definition of done:

- Unknown `?status=<name>` in the URL renders as a checked, clearable row in the status filter (today it filters but cannot be cleared from the UI).
- Pin tests for the list page's invalid `?sort=` fallback and its `role="alert"` error state.
- `VITE_API_PROXY` env var so `make e2e` can run the throwaway backend on a port other than 8000.
- Shell-quoting of directories with spaces in the resume command (the literal format in section 1 is unquoted; changing it needs an owner decision).
- Success announcements (`role="status"`) after posting a comment or changing status.

## 9. Architect amendments (binding, 2026-09-12)

`docs/ARCHITECT_MEMO.md` was produced in task 0.1. Its amendments **A1–A16 are binding** and
override sections 1–3 wherever they conflict. Every Test Writer and Implementer must read the
memo before touching a slice. Summary:

- **A1** Actor sub-schema `{session_id, name, directory|null}`; `human` → `{"human","human",null}`; no resume button when directory is null.
- **A2** Schema names: `Session, TicketListItem, TicketDetail, TimelineEntry, Actor, StatusItem, TicketsSummary`; requests `SessionIn, TicketCreate, TicketPatch, StatusChangeIn, CommentIn, NeedsHumanEyesIn`. `TimelineEntry` is one flat schema with nullable fields.
- **A3** `POST /tickets` → 201 `TicketDetail`; all ticket mutations → 200 `TicketDetail`; list → plain array; check order 422 → 404 → 400.
- **A4** PATCH is per-key replace with `exclude_unset`; one `field_change` per changed field; no-op writes nothing.
- **A5** `field_change` body: `<name> changed <field> from <old> to <new>`; `(none)` for null/empty; description → `<name> changed description`.
- **A6** `flag_change` body: `<name> flagged needs human eyes` / `<name> cleared needs human eyes`; no-op writes nothing.
- **A7** `reason` required on status change, optional on flag; comment body non-empty; status names stripped, case-sensitive.
- **A8** `updated_at` bumps on every non-no-op mutation incl. comments.
- **A9** List tie-breaks: `created_at`, then `id`, following `order`.
- **A10** Session fields nullable as listed; PUT keeps omitted keys, clears explicit nulls; list order `last_message_at desc` nulls last, then `created_at desc`.
- **A11** `cool-willow` is illustrative; tests read `name` back from the PUT response.
- **A12** Backend tests use `TestClient(api)` with paths relative to the API root (`/tickets`).
- **A13** `tracker/api/statuses.py`; `GET /statuses` → built-ins in canonical order then customs sorted by name.
- **A14** Register `GET /tickets/summary` before `GET /tickets/{id}`.
- **A15** `make gen-api` exports the schema with `manage.py export_openapi_schema` (no server) then runs `openapi-typescript`.
- **A16** Frontend client `baseUrl: window.location.origin`; Vite proxies `/api`; MSW handlers use relative paths.
