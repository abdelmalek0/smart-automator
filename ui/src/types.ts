// Shared TypeScript types for the QA Agent UI

export interface AuthUser {
  id: string
  username: string
  created_at: number
}

export type RunStatus =
  | 'pending'
  | 'running'
  | 'awaiting_human'
  | 'pass'
  | 'fail'
  | 'error'
  | 'cancelled'

export type StepStatus = 'running' | 'pass' | 'fail' | 'error'

export interface RunDraft {
  name?: string
  task: string
  success_criteria: string
  website_id?: string
  website_task_id?: string
  headless?: boolean
  max_steps?: number
  cdp_url?: string
  fresh_profile?: boolean
  source_run_id?: string
  use_replay_script?: boolean
}

export interface CriteriaVerdict {
  passed: boolean
  evidence: string
  reason: string
}

export interface RunSummary {
  run_id: string
  name?: string | null
  task: string
  success_criteria: string
  source_run_id?: string | null
  use_replay_script?: boolean
  has_replay_script?: boolean
  website_id?: string | null
  website_task_id?: string | null
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
  criteria_verdict?: CriteriaVerdict
  hitl_reason?: string | null
  hitl_source?: string | null
  hitl_deadline?: number | null
  human_controlling?: boolean
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
  turn_timing?: TurnTiming | null
  source?: 'human' | 'agent'
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

export interface ProjectTask {
  id: string
  name?: string | null
  task: string
  success_criteria: string
  headless: boolean
  max_steps: number
  cdp_url?: string
  fresh_profile?: boolean
  last_trained_run_id?: string | null
  has_trained_replay?: boolean
}

export interface ReplayStep {
  index: number
  action: string
  args: Record<string, unknown>
  element?: Record<string, unknown> | null
  url?: string
  page_title?: string
  element_label?: string
  verification_status?: string | null
  outcome?: string | null
  source?: string
}

export interface RunReplay {
  replay_steps: ReplayStep[]
  replay_script: string
}

export interface Project {
  id: string
  name: string
  url: string
  description: string
  context_prompt: string
  tasks: ProjectTask[]
}

/** @deprecated Use Project / ProjectTask — kept for localStorage migration */
export interface SuiteTask {
  id: string
  task: string
  headless: boolean
  max_steps: number
  cdp_url?: string
  fresh_profile?: boolean
}

/** @deprecated Use Project */
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
  models: string[]
}

export type BrowserSessionMode = 'cdp' | 'persistent' | 'ephemeral'

export interface ChromeProfile {
  id: string
  browser: string
  name: string
  user_data_dir: string
  profile_directory: string
}

export interface Config {
  provider: string
  model: string
  base_url: string
  api_key_set: boolean
  provider_keys_set: Record<string, boolean>
  provider_settings: Record<string, ProviderSettings>
  cdp_port: number
  cdp_url: string
  fresh_profile: boolean
  chrome_user_data: string
  chrome_profile_directory: string
  chrome_profile_mirror_path?: string
  effective_chrome_user_data: string
  effective_chrome_profile: string
  default_chrome_user_data: string
  browser_session_mode: BrowserSessionMode
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
  | { type: 'human_intervention_required'; reason: string; deadline?: number; source?: string; cycle?: number }
  | { type: 'human_control_started'; source?: string }
  | { type: 'take_control_pending' }
  | { type: 'human_intervention_ended'; cycle?: number }
  | { type: 'human_action'; action: string; args: Record<string, unknown>; result: string; step?: Step; cycle?: number }
  | { type: 'human_handoff'; analysis: Record<string, unknown>; actions: Array<Record<string, unknown>>; step?: Step; intervention_reason?: string; intervention_source?: string; start_url?: string; end_url?: string; cycle?: number }
  | { type: 'tokens_update'; tokens: number; prompt_tokens: number; completion_tokens: number; cache_tokens: number; cost_usd: number | null }
  | { type: 'turn_timing'; snapshot_ms?: number; llm_navigator_ms?: number; batch_ms?: number; settle_ms?: number; turn_ms?: number }
  | { type: 'error'; message: string }
  | { type: 'ping' }
  | { type: 'closed' }
