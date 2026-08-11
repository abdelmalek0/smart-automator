import type { RunStatus, Step, TurnTiming } from '@/types'

export function median(nums: number[]): number {
  if (nums.length === 0) return 0
  const sorted = [...nums].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1] + sorted[mid]) / 2
  }
  return sorted[mid]
}

function isTimedAgentStep(step: Step): boolean {
  if (step.source === 'human') return false
  return hasTurnTiming(step.turn_timing)
}

function stepActDurationMs(step: Step): number {
  if (!step.turn_timing) return 0
  return actDurationMs({
    ...step.turn_timing,
    turn_ms: step.turn_timing.turn_ms ?? step.elapsed_ms,
  })
}

export function aggregateTurnTiming(steps: Step[]): TurnTiming | null {
  const timedSteps = steps.filter(isTimedAgentStep)
  if (timedSteps.length === 0) return null

  const turnMs = median(
    timedSteps.map((step) => step.elapsed_ms ?? step.turn_timing?.turn_ms ?? 0),
  )

  return {
    turn_ms: turnMs,
    snapshot_ms: median(timedSteps.map((step) => step.turn_timing?.snapshot_ms ?? 0)),
    llm_navigator_ms: median(
      timedSteps.map((step) => step.turn_timing?.llm_navigator_ms ?? 0),
    ),
    batch_ms: median(timedSteps.map((step) => step.turn_timing?.batch_ms ?? 0)),
    settle_ms: median(timedSteps.map((step) => step.turn_timing?.settle_ms ?? 0)),
  }
}

export function aggregateTypicalActMs(steps: Step[]): number {
  const timedSteps = steps.filter(isTimedAgentStep)
  if (timedSteps.length === 0) return 0
  return median(timedSteps.map(stepActDurationMs))
}

export function hasTurnTiming(timing?: TurnTiming | null): timing is TurnTiming {
  if (!timing) return false
  return (
    (timing.turn_ms ?? 0) > 0 ||
    (timing.snapshot_ms ?? 0) > 0 ||
    (timing.llm_navigator_ms ?? 0) > 0
  )
}

export function actDurationMs(timing: TurnTiming): number {
  return Math.max(
    0,
    (timing.turn_ms ?? 0) - (timing.snapshot_ms ?? 0) - (timing.llm_navigator_ms ?? 0),
  )
}

export function executionModeLabel(useReplayScript?: boolean): 'Training' | 'Automatic execution' {
  return useReplayScript ? 'Automatic execution' : 'Training'
}

export function executionModeShortLabel(useReplayScript?: boolean): 'Training' | 'Automatic' {
  return useReplayScript ? 'Automatic' : 'Training'
}

export function executionModeChipClass(useReplayScript?: boolean): string {
  return useReplayScript
    ? 'bg-brand-blue/15 text-brand-blue border-brand-blue/30'
    : 'bg-warning/15 text-warning border-warning/30'
}

/** Automatic replay is only valid when a passed training (or automatic run) has a saved script. */
export function canRunUseAutomatic(run: {
  has_replay_script?: boolean
  use_replay_script?: boolean
  status: RunStatus
}): boolean {
  if (!run.has_replay_script) return false
  if (run.use_replay_script) return true
  return run.status === 'pass'
}

const ACTIVE_RUN_STATUSES: RunStatus[] = ['pending', 'running', 'awaiting_human']

export function isActiveRunStatus(status: RunStatus): boolean {
  return ACTIVE_RUN_STATUSES.includes(status)
}

export function liveRunRowClass(status: RunStatus): string {
  if (status === 'running') return 'bg-brand-blue/10 border-brand-blue'
  if (status === 'pending' || status === 'awaiting_human') return 'bg-warning/10 border-warning'
  return ''
}

export function liveRunStatusTextClass(status: RunStatus): string {
  if (status === 'running') return 'text-brand-blue font-medium'
  if (status === 'pending' || status === 'awaiting_human') return 'text-warning font-medium'
  return ''
}

export function liveRunHoverClass(status: RunStatus): string {
  if (status === 'running') return 'hover:bg-brand-blue/15'
  if (status === 'pending' || status === 'awaiting_human') return 'hover:bg-warning/15'
  return ''
}

export function statusBadgeVariant(
  status: RunStatus,
): 'running' | 'success' | 'destructive' | 'warning' | 'secondary' {
  switch (status) {
    case 'running':
      return 'running'
    case 'pending':
    case 'awaiting_human':
      return 'warning'
    case 'pass':
      return 'success'
    case 'fail':
    case 'error':
      return 'destructive'
    case 'cancelled':
      return 'secondary'
    default:
      return 'secondary'
  }
}

export function statusLabel(status: RunStatus): string {
  switch (status) {
    case 'pending':
      return 'Pending'
    case 'running':
      return 'Running'
    case 'awaiting_human':
      return 'Awaiting human'
    case 'pass':
      return 'Pass'
    case 'fail':
      return 'Fail'
    case 'error':
      return 'Error'
    case 'cancelled':
      return 'Cancelled'
    default:
      return status
  }
}

export function elapsedSeconds(startedAt: number, finishedAt: number | null): number {
  const end = finishedAt ?? Date.now() / 1000
  return Math.round(end - startedAt)
}

export function formatElapsed(secs: number): string {
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

export function formatDurationMs(ms: number): string {
  if (ms <= 0) return '0s'
  const secs = ms / 1000
  if (secs < 10) return `${secs.toFixed(1)}s`
  if (secs < 60) return `${Math.round(secs)}s`
  const minutes = Math.floor(secs / 60)
  const remainder = Math.round(secs % 60)
  return `${minutes}m ${remainder}s`
}
