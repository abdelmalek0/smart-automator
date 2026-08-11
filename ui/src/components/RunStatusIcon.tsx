import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RunStatus } from '@/types'

export type RunStatusIconStatus = RunStatus | 'connected' | 'offline'

const TERMINAL_DOT: Record<RunStatus, string> = {
  pending: 'bg-warning animate-pulse',
  running: 'bg-brand-blue animate-pulse-slow',
  awaiting_human: 'bg-warning animate-pulse',
  pass: 'bg-success',
  fail: 'bg-destructive',
  error: 'bg-destructive',
  cancelled: 'bg-muted-foreground',
}

function TerminalDot({ status }: { status: RunStatus }) {
  return (
    <span
      className={cn('inline-block h-2 w-2 shrink-0 rounded-full', TERMINAL_DOT[status] ?? 'bg-muted')}
    />
  )
}

export function RunStatusIcon({ status }: { status: RunStatusIconStatus }) {
  if (status === 'running') {
    return (
      <span
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-brand-blue/50 bg-brand-blue/15 text-brand-blue"
        aria-hidden
      >
        <Loader2 className="h-2.5 w-2.5 animate-spin" />
      </span>
    )
  }

  if (status === 'pending' || status === 'awaiting_human') {
    return (
      <span
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-warning/50 bg-warning/15"
        aria-hidden
      >
        <span
          className={cn(
            'h-2 w-2 rounded-full bg-warning',
            status === 'awaiting_human' && 'animate-pulse',
          )}
        />
      </span>
    )
  }

  if (status === 'connected') {
    return <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-success" aria-hidden />
  }

  if (status === 'offline') {
    return (
      <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-muted-foreground/50" aria-hidden />
    )
  }

  return <TerminalDot status={status} />
}
