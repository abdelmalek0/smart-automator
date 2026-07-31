import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from '@/components/layout/AppShell'
import RequireAuth from '@/components/RequireAuth'
import HomePage from '@/pages/HomePage'
import LoginPage from '@/pages/LoginPage'
import SignupPage from '@/pages/SignupPage'
import RunPage from '@/pages/RunPage'
import ProjectsPage from '@/pages/ProjectsPage'
import SettingsPage from '@/components/SettingsPage'
import { AuthProvider } from '@/contexts/AuthContext'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<AppShell />}>
              <Route index element={<HomePage />} />
              <Route path="runs/:runId" element={<RunPage />} />
              <Route path="projects" element={<ProjectsPage />} />
              <Route path="websites" element={<Navigate to="/projects" replace />} />
              <Route path="suites" element={<Navigate to="/projects" replace />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
