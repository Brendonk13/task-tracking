import { http, HttpResponse } from "msw"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { components } from "@/api/schema.d.ts"
import { AlertsPage } from "@/pages/AlertsPage"
import { alertsHandler, makeAlert, recordRequests, statefulAlerts } from "@/test/handlers"
import { server } from "@/test/msw"
import { renderWithProviders } from "@/test/render"

type PullRequestItem = components["schemas"]["PullRequestItem"]

// Layout convention: alerts render in a <table>; each alert is a role="row" (plus one header
// row). Rows are looked up by their accessible name (row text), so a row must contain the
// alert kind and message as visible text.
//
// Kind convention: the kind is shown verbatim, the way status names are elsewhere in this
// app ("needs-help"), so "pr_triaged" reads the same on screen as it does in the API.
//
// Ordering convention: rows appear in exactly the order GET /api/alerts returned them; the
// server sorts newest first (C5.6) and hides dismissed alerts, so the page never re-sorts.
//
// Ticket convention: an alert with a `ticket` shows a <Link to={`/tickets/${id}`}> whose
// accessible name contains the ticket title — the only thing a person recognises it by.
//
// Pull-request convention: an alert with a `pull_request` shows an external link named
// "PR #<number>" pointing at the PR on GitHub. `Alert.pull_request` is only `{id, number}`
// (schemas.PullRequestRef), so the url has to come from GET /api/pull-requests, matched on
// the PR id. If the backend ever grows `PullRequestRef.url`, this handler can go away and
// the assertion stays exactly as it is.
//
// Resume convention (F3.5, components/sessions/ResumeSessionButton): an alert whose
// `session` has a directory gets a <button aria-label="Resume session <name>">; a session
// with no directory (a managed run that never had one) gets no button, because there is
// nowhere to cd to.

const GITHUB = "https://github.com/mosaic-avantos/avantos/pull"

/** A `PullRequestItem` as GET /api/pull-requests returns it; only id, number and url matter here. */
function makePullRequest(id: number, number: number): PullRequestItem {
  return {
    id,
    repo: "mosaic-avantos/avantos",
    number,
    url: `${GITHUB}/${number}`,
    title: `Pull request ${number}`,
    branch: `brendonkeirle/con-${number}`,
    head_sha: "0f1e2d3",
    state: "open",
    author: "Brendonk13",
    ticket_id: null,
    comment_count: 0,
    last_triage_session: null,
  }
}

describe("AlertsPage", () => {
  it("lists alerts newest first with kind, message, ticket link, PR link and session resume button", async () => {
    // Ids run 3, 1, 4, 2 while created_at runs newest → oldest: the only order that explains
    // the rows below is "exactly what the server sent".
    const cronError = makeAlert({
      id: 3,
      kind: "cron_error",
      message: "LINEAR_API_KEY is not set, so no tickets were imported",
      // A managed session that ran without a directory: nothing to resume into.
      session: { session_id: "sess-cron", name: "brisk-heron", directory: null },
      created_at: "2026-09-12T11:00:00Z",
    })
    const prTriaged = makeAlert({
      id: 1,
      kind: "pr_triaged",
      message: "PR #42 triaged: 3 comments judged, waiting on a human review",
      ticket: { id: 7, title: "Fix the login redirect" },
      pull_request: { id: 101, number: 42 },
      session: { session_id: "sess-1", name: "cool-willow", directory: "/home/dev/app" },
      created_at: "2026-09-12T10:30:00Z",
    })
    const prUnlinked = makeAlert({
      id: 4,
      kind: "pr_unlinked",
      message: "PR #43 matches no ticket: Bump the flaky timeout",
      pull_request: { id: 102, number: 43 },
      created_at: "2026-09-12T10:00:00Z",
    })
    const newTicket = makeAlert({
      id: 2,
      kind: "new_ticket",
      message: "CON-7 Import Linear issues",
      ticket: { id: 9, title: "Import Linear issues" },
      created_at: "2026-09-11T09:00:00Z",
    })
    server.use(
      alertsHandler([cronError, prTriaged, prUnlinked, newTicket]),
      http.get("/api/pull-requests", () =>
        HttpResponse.json([makePullRequest(101, 42), makePullRequest(102, 43)]),
      ),
    )
    renderWithProviders(<AlertsPage />)

    await screen.findByText(prTriaged.message)

    // Header row + four alert rows, in the server's order, each naming its kind.
    const [, ...alertRows] = screen.getAllByRole("row")
    expect(
      alertRows.map((row) => [
        ["cron_error", "pr_triaged", "pr_unlinked", "new_ticket"].find((kind) =>
          within(row).queryByText(kind),
        ),
        within(row).queryByText(/^(LINEAR_API_KEY|PR #4[23]|CON-7)/)?.textContent,
      ]),
    ).toEqual([
      ["cron_error", cronError.message],
      ["pr_triaged", prTriaged.message],
      ["pr_unlinked", prUnlinked.message],
      ["new_ticket", newTicket.message],
    ])

    // The ticket an alert is about is a link into this app.
    const triagedRow = screen.getByRole("row", { name: /triaged/i })
    expect(
      within(triagedRow).getByRole("link", { name: /Fix the login redirect/i }),
    ).toHaveAttribute("href", "/tickets/7")
    const newTicketRow = screen.getByRole("row", { name: /CON-7/ })
    expect(within(newTicketRow).getByRole("link", { name: /Import Linear issues/i })).toHaveAttribute(
      "href",
      "/tickets/9",
    )

    // The pull request is a link out to GitHub.
    expect(within(triagedRow).getByRole("link", { name: "PR #42" })).toHaveAttribute(
      "href",
      `${GITHUB}/42`,
    )
    const unlinkedRow = screen.getByRole("row", { name: /matches no ticket/i })
    expect(within(unlinkedRow).getByRole("link", { name: "PR #43" })).toHaveAttribute(
      "href",
      `${GITHUB}/43`,
    )

    // Only the alert whose session has a directory can be resumed.
    expect(
      within(triagedRow).getByRole("button", { name: "Resume session cool-willow" }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /^Resume session/ })).toHaveLength(1)
  })

  // Dismiss convention: every row carries a control whose accessible name is "Dismiss"
  // (scoped per row, so a test finds it with `within(row)`). Clicking it posts to
  // /api/alerts/{id}/dismiss; the backend hides dismissed alerts, so the row goes away
  // once the list is refetched — the page itself never filters.
  it("dismiss removes the alert and requests POST /api/alerts/{id}/dismiss", async () => {
    const user = userEvent.setup()
    const requests = recordRequests()
    const unlinked = makeAlert({
      id: 6,
      kind: "pr_unlinked",
      message: "PR #44 matches no ticket: Bump the flaky timeout",
      created_at: "2026-09-12T10:00:00Z",
    })
    const newTicket = makeAlert({
      id: 5,
      kind: "new_ticket",
      message: "CON-8 Import Linear issues",
      created_at: "2026-09-11T09:00:00Z",
    })
    const alerts = statefulAlerts([unlinked, newTicket])
    server.use(...alerts.handlers, http.get("/api/pull-requests", () => HttpResponse.json([])))
    renderWithProviders(<AlertsPage />)

    const row = await screen.findByRole("row", { name: /matches no ticket/i })
    await user.click(within(row).getByRole("button", { name: /^dismiss$/i }))

    // The dismissal went to this alert's own endpoint, as a POST.
    await waitFor(() => expect(alerts.dismissRequests).toEqual([6]))
    expect(requests).toContain("/api/alerts/6/dismiss")

    // ...and the row is gone, while the alert nobody dismissed stays.
    await waitFor(() => expect(screen.queryByText(unlinked.message)).toBeNull())
    expect(screen.getByText(newTicket.message)).toBeInTheDocument()
  })
})
