import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from '@/components/layout/AppShell'
import HomePage from '@/pages/HomePage'
import RunPage from '@/pages/RunPage'
import ToolsPage from '@/components/ToolsPage'
import WebsitesPage from '@/pages/WebsitesPage'
import SettingsPage from '@/components/SettingsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="runs/:runId" element={<RunPage />} />
          <Route path="tools" element={<ToolsPage />} />
          <Route path="websites" element={<WebsitesPage />} />
          <Route path="suites" element={<Navigate to="/websites" replace />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
