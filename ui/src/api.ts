import type { ChromeProfile, Config, PricingEntry, Project, ProjectTask, RunDetails, RunSummary } from './types'
import { normalizeProvider } from './providers'

const BASE = '/api'

export type ConfigUpdatePayload = {
  provider?: string
  base_url?: string
  model?: string
  api_key?: string
  fresh_profile?: boolean
  chrome_user_data?: string
  chrome_profile_directory?: string
  cdp_url?: string
}

function formatApiError(status: number, text: string): string {
  try {
    const body = JSON.parse(text) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail.trim()) {
      return body.detail
    }
  } catch {
    // fall through
  }
  return text.trim() || `Request failed (${status})`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (res.status === 401) {
    throw new Error('Not authenticated')
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(formatApiError(res.status, text))
  }
  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

export type AuthSetup = {
  needs_registration: boolean
  registration_open: boolean
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export function getAuthSetup(): Promise<AuthSetup> {
  return request('/auth/setup')
}

export function getMe(): Promise<{ user: import('./types').AuthUser } | null> {
  return fetch(`${BASE}/auth/me`, { credentials: 'include' }).then(async (res) => {
    if (res.status === 401) return null
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText)
      throw new Error(`${res.status}: ${text}`)
    }
    return res.json() as Promise<{ user: import('./types').AuthUser }>
  })
}

export function login(username: string, password: string): Promise<{ user: import('./types').AuthUser }> {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function register(username: string, password: string): Promise<{ user: import('./types').AuthUser }> {
  return request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function logout(): Promise<void> {
  await request('/auth/logout', { method: 'POST' })
}

// ── Runs ──────────────────────────────────────────────────────────────────────

export function listRuns(): Promise<RunSummary[]> {
  return request('/runs')
}

export function getRun(runId: string): Promise<RunDetails> {
  return request(`/runs/${runId}`)
}

export async function startRun(payload: {
  name?: string
  task: string
  success_criteria: string
  headless: boolean
  max_steps: number
  cdp_url?: string
  fresh_profile?: boolean
  website_id?: string
  website_task_id?: string
  source_run_id?: string
  use_replay_script?: boolean
}): Promise<RunSummary> {
  return request('/runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function cancelRun(runId: string): Promise<void> {
  await request(`/runs/${runId}`, { method: 'DELETE' })
}

export async function deleteRun(runId: string): Promise<void> {
  await request(`/runs/${runId}?purge=true`, { method: 'DELETE' })
}

export async function takeControl(
  runId: string,
): Promise<{ ok: boolean; human_controlling: boolean; pending?: boolean }> {
  return request(`/runs/${runId}/take-control`, { method: 'POST' })
}

export async function returnControl(runId: string): Promise<{ ok: boolean; human_controlling: boolean }> {
  return request(`/runs/${runId}/return-control`, { method: 'POST' })
}

// ── Config ────────────────────────────────────────────────────────────────────

export function getConfig(): Promise<Config> {
  return request('/config')
}

export function listChromeProfiles(): Promise<ChromeProfile[]> {
  return request('/chrome-profiles')
}

export function checkConfig(payload?: {
  provider?: string
  base_url?: string
  model?: string
  api_key?: string
}): Promise<{ ok: boolean; error?: string }> {
  return request('/config/check', {
    method: 'POST',
    body: JSON.stringify(payload ?? {}),
  })
}

export async function updateConfig(payload: ConfigUpdatePayload): Promise<Config> {
  return request('/config', { method: 'PUT', body: JSON.stringify(payload) })
}

/** Whether the selected provider has a stored API key (dedicated slot or legacy fallback). */
export function isProviderApiKeySet(provider: string, config: Config | undefined): boolean {
  if (!config) return false
  const canonical = normalizeProvider(provider)
  if (config.provider_keys_set?.[canonical]) return true
  const hasDedicated = Object.values(config.provider_keys_set ?? {}).some(Boolean)
  if (!hasDedicated && canonical === normalizeProvider(config.provider) && config.api_key_set) {
    return true
  }
  return false
}

// ── Pricing ───────────────────────────────────────────────────────────────────

export function getPricing(): Promise<PricingEntry[]> {
  return request('/pricing')
}

export async function savePricing(entries: PricingEntry[]): Promise<void> {
  await request('/pricing', { method: 'PUT', body: JSON.stringify(entries) })
}

// ── Projects (API path: /websites) ─────────────────────────────────────────────

export function listProjects(): Promise<Project[]> {
  return request('/websites')
}

export function getProject(projectId: string): Promise<Project> {
  return request(`/websites/${projectId}`)
}

export async function createProject(payload: {
  name: string
  url?: string
  context_prompt?: string
}): Promise<Project> {
  return request('/websites', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateProject(
  projectId: string,
  payload: { name?: string; url?: string; context_prompt?: string },
): Promise<Project> {
  return request(`/websites/${projectId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteProject(projectId: string): Promise<void> {
  await request(`/websites/${projectId}`, { method: 'DELETE' })
}

export async function createProjectTask(
  projectId: string,
  payload: Omit<ProjectTask, 'id'>,
): Promise<ProjectTask> {
  return request(`/websites/${projectId}/tasks`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateProjectTask(
  projectId: string,
  taskId: string,
  payload: Partial<Omit<ProjectTask, 'id'>>,
): Promise<ProjectTask> {
  return request(`/websites/${projectId}/tasks/${taskId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteProjectTask(projectId: string, taskId: string): Promise<void> {
  await request(`/websites/${projectId}/tasks/${taskId}`, { method: 'DELETE' })
}
