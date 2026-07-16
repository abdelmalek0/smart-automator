import type { RunStatus, TurnTiming } from '@/types'

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

export function statusBadgeVariant(
  status: RunStatus,
): 'running' | 'success' | 'destructive' | 'warning' | 'secondary' {
  switch (status) {
    case 'running':
    case 'pending':
      return 'running'
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
