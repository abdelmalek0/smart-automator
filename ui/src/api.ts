import type { Config, PricingEntry, RunDetails, RunSummary, Tool, Website, WebsiteTask } from './types'
import { normalizeProvider } from './providers'

const BASE = '/api'

export type ConfigUpdatePayload = {
  provider?: string
  base_url?: string
  model?: string
  api_key?: string
  fresh_profile?: boolean
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

// ── Runs ──────────────────────────────────────────────────────────────────────

export function listRuns(): Promise<RunSummary[]> {
  return request('/runs')
}

export function getRun(runId: string): Promise<RunDetails> {
  return request(`/runs/${runId}`)
}

export async function startRun(payload: {
  task: string
  headless: boolean
  max_steps: number
  cdp_url?: string
  fresh_profile?: boolean
  website_id?: string
}): Promise<RunSummary> {
  return request('/runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function cancelRun(runId: string): Promise<void> {
  await request(`/runs/${runId}`, { method: 'DELETE' })
}

// ── Tools ─────────────────────────────────────────────────────────────────────

export function listTools(): Promise<Tool[]> {
  return request('/tools')
}

// ── Config ────────────────────────────────────────────────────────────────────

export function getConfig(): Promise<Config> {
  return request('/config')
}

export function checkConfig(): Promise<{ ok: boolean; error?: string }> {
  return request('/config/check')
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

// ── Websites ────────────────────────────────────────────────────────────────────

export function listWebsites(): Promise<Website[]> {
  return request('/websites')
}

export function getWebsite(websiteId: string): Promise<Website> {
  return request(`/websites/${websiteId}`)
}

export async function createWebsite(payload: {
  name: string
  url?: string
  context_prompt?: string
}): Promise<Website> {
  return request('/websites', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateWebsite(
  websiteId: string,
  payload: { name?: string; url?: string; context_prompt?: string },
): Promise<Website> {
  return request(`/websites/${websiteId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteWebsite(websiteId: string): Promise<void> {
  await request(`/websites/${websiteId}`, { method: 'DELETE' })
}

export async function createWebsiteTask(
  websiteId: string,
  payload: Omit<WebsiteTask, 'id'>,
): Promise<WebsiteTask> {
  return request(`/websites/${websiteId}/tasks`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateWebsiteTask(
  websiteId: string,
  taskId: string,
  payload: Partial<Omit<WebsiteTask, 'id'>>,
): Promise<WebsiteTask> {
  return request(`/websites/${websiteId}/tasks/${taskId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteWebsiteTask(websiteId: string, taskId: string): Promise<void> {
  await request(`/websites/${websiteId}/tasks/${taskId}`, { method: 'DELETE' })
}
