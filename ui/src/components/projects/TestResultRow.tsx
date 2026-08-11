import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { RunStatusIcon } from '@/components/RunStatusIcon'
import { SuiteStatusIcon } from '@/components/projects/SuiteProgressPanel'
import { formatRunStartedLabel } from '@/lib/run-threads'
import { statusLabel } from '@/lib/run-status'
import type { TestRowStatus } from '@/lib/project-task-status'
import type { ProjectTask, RunSummary } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  task: ProjectTask
  status: TestRowStatus
  attemptRuns?: RunSummary[]
}

function StatusGlyph({ status }: { status: TestRowStatus }) {
  if (status.kind === 'suite' && status.suiteStatus) {
    return <SuiteStatusIcon status={status.suiteStatus} size="sm" />
  }

  if (status.kind === 'never') {
    return (
      <span
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-dashed border-muted-foreground/35"
        aria-hidden
      />
    )
  }

  if (status.runStatus) {
    return <RunStatusIcon status={status.runStatus} />
  }

  return null
}

function ResultContent({
  status,
  timeLabel,
}: {
  status: TestRowStatus
  timeLabel: string | null
}) {
  if (status.kind === 'never') {
    return <span className="italic">Never run</span>
  }

  return (
    <>
      <span>{status.label}</span>
      {timeLabel && (
        <>
          <span aria-hidden> · </span>
          <span className="mono">{timeLabel}</span>
        </>
      )}
    </>
  )
}

export default function TestResultRow({ task, status, attemptRuns = [] }: Props) {
  const [expanded, setExpanded] = useState(false)
  const displayName = task.name || 'Untitled test'
  const timeLabel =
    status.startedAt != null ? formatRunStartedLabel(status.startedAt) : null
  const canExpand = attemptRuns.length > 1
  const isClickable = Boolean(status.runId)

  const rowInner = (
    <>
      <div className="shrink-0" aria-hidden>
        <StatusGlyph status={status} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold leading-snug truncate">{displayName}</p>
        <p className="text-[11px] text-muted-foreground truncate">
          <ResultContent status={status} timeLabel={timeLabel} />
        </p>
      </div>
      {canExpand && (
        <button
          type="button"
          className="shrink-0 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-expanded={expanded}
          aria-label={expanded ? 'Hide attempt history' : 'Show attempt history'}
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            setExpanded((v) => !v)
          }}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>
      )}
    </>
  )

  return (
    <div
      className={cn(
        'rounded-xl transition-colors duration-150',
        expanded && 'bg-accent/20',
      )}
    >
      {isClickable ? (
        <Link
          to={`/runs/${status.runId}`}
          className={cn(
            'flex items-center gap-3 px-2 py-3 sm:px-3',
            'hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          )}
          aria-label={`Open latest run for ${displayName}: ${status.label}`}
        >
          {rowInner}
        </Link>
      ) : (
        <div className="flex items-center gap-3 px-2 py-3 sm:px-3">{rowInner}</div>
      )}

      {expanded && canExpand && (
        <div className="mt-0 mb-2 ml-8 space-y-1 border-l border-border/60 pl-3">
          {attemptRuns.map((run) => (
            <Link
              key={run.run_id}
              to={`/runs/${run.run_id}`}
              className={cn(
                'flex items-center gap-2 rounded-md px-2 py-1.5 text-[11px]',
                'text-muted-foreground hover:text-foreground hover:bg-accent/40 transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              )}
            >
              <RunStatusIcon status={run.status} />
              <span>{statusLabel(run.status)}</span>
              <span aria-hidden>·</span>
              <span className="mono">{formatRunStartedLabel(run.started_at)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
