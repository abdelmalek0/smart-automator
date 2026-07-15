// Shared TypeScript types for the QA Agent UI

export type RunStatus =
  | 'pending'
  | 'running'
  | 'pass'
  | 'fail'
  | 'error'
  | 'cancelled'

export type StepStatus = 'running' | 'pass' | 'fail' | 'error'

export interface RunDraft {
  task: string
  website_id?: string
  headless?: boolean
  max_steps?: number
  cdp_url?: string
  fresh_profile?: boolean
}

export interface RunSummary {
  run_id: string
  task: string
  website_id?: string | null
  headless?: boolean
  max_steps?: number
  cdp_url?: string | null
  fresh_profile?: boolean
  status: RunStatus
  step_count: number
  started_at: number
  finished_at: number | null
  summary: string
  tokens: number
  prompt_tokens: number
  completion_tokens: number
  cache_tokens: number
  cost_usd: number | null
}

export interface Step {
  index: number
  thought: string
  action: string
  args: Record<string, unknown>
  result: string
  status: StepStatus
  screenshot_url: string | null
  elapsed_ms: number
  atomic_step?: number | null
}

export interface AtomicStep {
  step: number
  action: 'navigate' | 'interact' | 'choose' | 'assert'
  target: string
  value: string | null
  note: string | null
}

export interface Plan {
  completed?: string[]
  remaining?: string[]
  skipped?: string[]
  in_progress?: string | null
}

export interface RunProgress {
  seq?: number
  app_context?: Record<string, unknown>
  current_atomic_step?: number | null
  atomic_progress?: {
    current?: number | null
    total?: number
    completed?: number
    validated?: number
  }
  screen_summary?: string
  state_digest?: string
}

export interface TurnTiming {
  snapshot_ms?: number
  llm_navigator_ms?: number
  batch_ms?: number
  settle_ms?: number
  turn_ms?: number
}

export interface RunDetails extends RunSummary {
  steps: Step[]
  plan: Plan
  new_tools: string[]
  website_id?: string | null
  extracted_steps?: AtomicStep[]
  current_atomic_step?: number | null
  progress?: RunProgress
  app_context?: Record<string, unknown>
  turn_timing?: TurnTiming
}

export interface Tool {
  name: string
  doc: string
  signature: string
}

export interface WebsiteTask {
  id: string
  task: string
  headless: boolean
  max_steps: number
  cdp_url?: string
  fresh_profile?: boolean
}

export interface Website {
  id: string
  name: string
  url: string
  context_prompt: string
  tasks: WebsiteTask[]
}

/** @deprecated Use Website / WebsiteTask — kept for localStorage migration */
export interface SuiteTask {
  id: string
  task: string
  headless: boolean
  max_steps: number
  cdp_url?: string
  fresh_profile?: boolean
}

/** @deprecated Use Website */
export interface Suite {
  id: string
  name: string
  tasks: SuiteTask[]
}

export interface PricingEntry {
  provider: string
  model: string
  input: number      // USD per 1M input tokens
  output: number     // USD per 1M output tokens
  cache_read: number // USD per 1M cache-read tokens
}

export interface ProviderSettings {
  base_url: string
  model: string
  models: string[]
}

export interface Config {
  provider: string
  model: string
  base_url: string
  api_key_set: boolean
  provider_keys_set: Record<string, boolean>
  provider_settings: Record<string, ProviderSettings>
  cdp_port: number
  fresh_profile: boolean
  chrome_user_data: string
}

// WebSocket event types
export type WSEvent =
  | { type: 'snapshot'; run: RunDetails }
  | { type: 'step_start'; step: Step }
  | { type: 'step_end'; step: Step }
  | { type: 'plan_update'; plan: Plan }
  | { type: 'steps_extracted'; steps: AtomicStep[] }
  | { type: 'milestones_updated'; mutation: string; milestones: AtomicStep[]; current_index: number; seq?: number; progress?: RunProgress }
  | { type: 'atomic_step_focus'; step: number; total: number; atomic: AtomicStep }
  | { type: 'atomic_step_done'; step: number; summary: string; seq?: number; progress?: RunProgress }
  | { type: 'validation_blocked'; atomic_step?: number | null; message: string; passed: boolean; seq?: number; progress?: RunProgress }
  | { type: 'validation_passed'; atomic_step?: number | null; message: string; passed: boolean; seq?: number; progress?: RunProgress }
  | { type: 'atomic_step_completed'; atomic_step?: number | null; message: string; passed: boolean; seq?: number; progress?: RunProgress }
  | { type: 'run_finished'; status: string; summary: string; seq?: number; progress?: RunProgress }
  | { type: 'report_ready'; report_path: string; seq?: number; progress?: RunProgress }
  | { type: 'tool_written'; name: string }
  | { type: 'done'; status: string; summary: string }
  | { type: 'status'; status: string }
  | { type: 'tokens_update'; tokens: number; prompt_tokens: number; completion_tokens: number; cache_tokens: number; cost_usd: number | null }
  | { type: 'turn_timing'; snapshot_ms?: number; llm_navigator_ms?: number; batch_ms?: number; settle_ms?: number; turn_ms?: number }
  | { type: 'error'; message: string }
  | { type: 'ping' }
  | { type: 'closed' }
