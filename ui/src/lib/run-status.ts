import type { RunStatus } from '@/types'

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
