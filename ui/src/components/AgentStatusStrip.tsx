import { useRunStartGate, type AgentPhase } from '@/hooks/useRunStartGate'
import { elapsedSeconds, formatElapsed } from '@/lib/run-status'
import { cn } from '@/lib/utils'

const PHASE_TITLE: Record<AgentPhase, string> = {
  offline: 'Agent is offline',
  connected: 'Agent is connected',
  starting: 'Agent is starting…',
  running: 'Agent is running',
  awaiting_human: 'Agent is waiting',
}

const PHASE_DOT: Record<AgentPhase, string> = {
  offline: 'bg-muted-foreground/50',
  connected: 'bg-success',
  starting: 'bg-warning',
  running: 'bg-brand-blue',
  awaiting_human: 'bg-warning',
}

interface Props {
  embedded?: boolean
}

export default function AgentStatusStrip({ embedded = false }: Props) {
  const { agentPhase, activeRun } = useRunStartGate()

  const title = PHASE_TITLE[agentPhase]
  const runLabel = activeRun ? activeRun.name || activeRun.task : null
  const duration =
    activeRun
      ? formatElapsed(elapsedSeconds(activeRun.started_at, activeRun.finished_at))
      : null

  const subline =
    runLabel && duration ? `${runLabel} · ${duration}` : runLabel

  return (
    <div
      className={cn(
        'w-full min-w-0 rounded-md border border-border/60 bg-muted/20',
        embedded ? 'px-2.5 py-2' : 'mx-3 mb-2 px-2.5 py-2',
      )}
      role="status"
      aria-live="polite"
      aria-atomic="true"
      title={subline ?? title}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={cn('inline-block h-2 w-2 shrink-0 rounded-full', PHASE_DOT[agentPhase])}
          aria-hidden
        />
        <p className="truncate text-xs font-semibold leading-snug">{title}</p>
      </div>
      {subline ? (
        <p className="mt-0.5 truncate pl-4 text-[11px] text-muted-foreground">{subline}</p>
      ) : agentPhase === 'offline' ? (
        <p className="mt-0.5 pl-4 text-[11px] text-muted-foreground">Run the Connect app</p>
      ) : null}
    </div>
  )
}
