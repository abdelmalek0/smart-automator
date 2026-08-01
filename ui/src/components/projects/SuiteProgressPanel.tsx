import { Link } from 'react-router-dom'
import { Check, Loader2, Minus, Square, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ProjectSuiteRunner, SuiteTaskResult, SuiteTaskStatus } from '@/hooks/useProjectSuiteRunner'
import {
  isTerminalSuiteStatus,
  suiteStatusLabel,
  taskDisplayName,
} from '@/hooks/useProjectSuiteRunner'
import type { Project } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  project: Project
  suite: ProjectSuiteRunner
}

export function SuiteStatusIcon({
  status,
  size = 'md',
}: {
  status: SuiteTaskStatus
  size?: 'sm' | 'md'
}) {
  const box = size === 'sm' ? 'h-5 w-5' : 'h-7 w-7'
  const icon = size === 'sm' ? 'h-3 w-3' : 'h-3.5 w-3.5'

  if (status === 'running') {
    return (
      <span
        className={cn(
          'inline-flex items-center justify-center rounded-full border border-primary/50 bg-primary/10 text-primary',
          box,
        )}
      >
        <Loader2 className={cn(icon, 'animate-spin')} />
      </span>
    )
  }

  if (status === 'pass') {
    return (
      <span
        className={cn(
          'inline-flex items-center justify-center rounded-full border border-success/40 bg-success/15 text-success',
          box,
        )}
      >
        <Check className={icon} strokeWidth={2.5} />
      </span>
    )
  }

  if (status === 'fail' || status === 'error') {
    return (
      <span
        className={cn(
          'inline-flex items-center justify-center rounded-full border border-destructive/40 bg-destructive/15 text-destructive',
          box,
        )}
      >
        <X className={icon} strokeWidth={2.5} />
      </span>
    )
  }

  if (status === 'cancelled' || status === 'skipped') {
    return (
      <span
        className={cn(
          'inline-flex items-center justify-center rounded-full border border-border bg-muted/50 text-muted-foreground',
          box,
        )}
      >
        <Minus className={icon} />
      </span>
    )
  }

  // queued
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-full border border-dashed border-muted-foreground/40 bg-transparent',
        box,
      )}
    />
  )
}

/** @deprecated Prefer SuiteStatusIcon — kept for any remaining chip callers */
export function suiteStatusChipClass(status: SuiteTaskResult['status']): string {
  switch (status) {
    case 'pass':
      return 'border-success/40 text-success bg-success/10'
    case 'fail':
    case 'error':
      return 'border-destructive/40 text-destructive bg-destructive/10'
    case 'running':
      return 'border-primary/40 text-primary bg-primary/10'
    case 'cancelled':
    case 'skipped':
      return 'border-border text-muted-foreground bg-muted/40'
    default:
      return 'border-border text-muted-foreground'
  }
}

export default function SuiteProgressPanel({ project, suite }: Props) {
  const { state, stop, reset, isRunning, successCount, failedCount, totalsReady } = suite
  if (state.projectId !== project.id || state.phase === 'idle') return null

  const total = state.results.length
  const completed = state.results.filter((r) => isTerminalSuiteStatus(r.status)).length
  const progressPct = total === 0 ? 0 : Math.round((completed / total) * 100)
  const current = project.tasks.find((t) => t.id === state.currentTaskId)
  const currentName = current ? taskDisplayName(current) : null
  const skipped = total - successCount - failedCount

  const title = isRunning
    ? 'Running suite'
    : state.phase === 'cancelled'
      ? 'Suite stopped'
      : 'Suite complete'

  return (
    <div className="rounded-xl border border-border/80 bg-card/60 p-4 space-y-4 animate-in fade-in-0 slide-in-from-top-1 duration-300">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-0.5">
          <p className="text-sm font-semibold tracking-tight">{title}</p>
          {isRunning && currentName ? (
            <p className="text-xs text-muted-foreground truncate">
              Now: <span className="text-foreground/90">{currentName}</span>
            </p>
          ) : !isRunning ? (
            <p className="text-xs text-muted-foreground">
              {completed} of {total} tests finished
            </p>
          ) : null}
        </div>
        <div className="shrink-0">
          {isRunning ? (
            <Button size="sm" variant="outline" className="h-8" onClick={() => void stop()}>
              <Square className="h-3 w-3" />
              Stop
            </Button>
          ) : (
            <Button size="sm" variant="ghost" className="h-8" onClick={reset}>
              Dismiss
            </Button>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative flex-1 h-2 rounded-full bg-muted overflow-hidden">
          <div
            className={cn(
              'absolute inset-y-0 left-0 rounded-full bg-primary transition-[width] duration-500 ease-out',
              isRunning && progressPct < 100 && 'after:absolute after:inset-y-0 after:right-0 after:w-8 after:bg-gradient-to-r after:from-transparent after:to-primary/40 after:animate-pulse',
            )}
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <span className="mono text-sm font-medium tabular-nums text-foreground/90 shrink-0 w-12 text-right">
          {completed}
          <span className="text-muted-foreground"> / {total}</span>
        </span>
      </div>

      {totalsReady && (
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-lg border border-success/25 bg-success/10 px-3 py-2.5">
            <p className="text-[10px] uppercase tracking-wide text-success/80 font-medium">
              Successful
            </p>
            <p className="text-2xl font-semibold tabular-nums text-success leading-none mt-1">
              {successCount}
            </p>
          </div>
          <div className="rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2.5">
            <p className="text-[10px] uppercase tracking-wide text-destructive/80 font-medium">
              Failed
            </p>
            <p className="text-2xl font-semibold tabular-nums text-destructive leading-none mt-1">
              {failedCount}
            </p>
          </div>
          {skipped > 0 && (
            <p className="col-span-2 text-[11px] text-muted-foreground">Skipped: {skipped}</p>
          )}
        </div>
      )}

      <ul className="space-y-1">
        {state.results.map((result) => {
          const task = project.tasks.find((t) => t.id === result.taskId)
          const active = result.status === 'running'
          return (
            <li
              key={result.taskId}
              className={cn(
                'flex items-center gap-3 rounded-lg px-2.5 py-2 transition-colors',
                active && 'bg-primary/5 border-l-2 border-l-primary pl-2 animate-in fade-in-0 slide-in-from-left-1 duration-300',
                !active && result.status === 'queued' && 'opacity-60',
                !active && isTerminalSuiteStatus(result.status) && 'opacity-90',
              )}
            >
              <SuiteStatusIcon status={result.status} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate leading-snug">
                  {task ? taskDisplayName(task) : result.taskId}
                </p>
                <p className="text-[11px] text-muted-foreground">{suiteStatusLabel(result.status)}</p>
              </div>
              {result.runId && (
                <Link
                  to={`/runs/${result.runId}`}
                  className="text-xs font-medium text-primary hover:underline shrink-0"
                >
                  Open
                </Link>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
