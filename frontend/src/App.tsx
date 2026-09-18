import { Navigate, Route, Routes } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { AlertsPage } from "@/pages/AlertsPage"
import { SessionsPage } from "@/pages/SessionsPage"
import { TicketDetailPage } from "@/pages/TicketDetailPage"
import { TicketListPage } from "@/pages/TicketListPage"

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<TicketListPage />} />
        <Route path="tickets/:id" element={<TicketDetailPage />} />
        <Route path="sessions" element={<SessionsPage />} />
        <Route path="alerts" element={<AlertsPage />} />
      </Route>
      {/* Unknown paths fall back to the ticket list. */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
