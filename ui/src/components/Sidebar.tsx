import { Link } from 'react-router-dom'
import {
  Globe,
  Home,
  Plus,
  RotateCcw,
  Settings,
  Wrench,
} from 'lucide-react'
import logoUrl from '../../logo.jpeg'
import type { RunSummary, RunStatus } from '@/types'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { NavLink } from '@/components/layout/AppShell'
import { useRunModal } from '@/contexts/RunModalContext'
import { runSummaryToDraft } from '@/lib/run-draft'
import { elapsedSeconds, formatElapsed } from '@/lib/run-status'
import { cn } from '@/lib/utils'

interface Props {
  runs: RunSummary[]
  activeRunId: string | null
}

function StatusDot({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, string> = {
    pending: 'bg-warning animate-pulse',
    running: 'bg-brand-blue animate-pulse-slow',
    pass: 'bg-success',
    fail: 'bg-destructive',
    error: 'bg-brand-orange',
    cancelled: 'bg-muted-foreground',
  }
  return (
    <span
      className={cn('inline-block w-2 h-2 rounded-full flex-shrink-0', map[status] ?? 'bg-muted')}
    />
  )
}

export default function Sidebar({ runs, activeRunId }: Props) {
  const { openNewRun } = useRunModal()

  return (
    <aside className="w-64 flex-shrink-0 bg-card border-r border-border flex flex-col h-full">
      <div className="px-4 py-4 border-b border-border">
        <Link
          to="/"
          className="flex items-center gap-2.5 mb-4 hover:opacity-90 transition-opacity"
        >
          <img
            src={logoUrl}
            alt="Smart Automator"
            className="w-8 h-8 rounded-md object-cover flex-shrink-0 ring-1 ring-border"
          />
          <div className="flex flex-col leading-tight min-w-0">
            <span className="font-semibold text-sm tracking-tight truncate">Smart Automator</span>
            <span className="font-medium text-[10px] tracking-widest text-primary uppercase">
              Browser Agent
            </span>
          </div>
        </Link>
        <Button onClick={() => openNewRun()} className="w-full" size="sm">
          <Plus className="h-4 w-4" />
          New Run
        </Button>
      </div>

      <ScrollArea className="flex-1 py-2">
        {runs.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center px-4 pt-6">No runs yet</p>
        ) : (
          <div className="space-y-0.5 px-2">
            {runs.map((run) => {
              const active = activeRunId === run.run_id
              return (
                <div
                  key={run.run_id}
                  className={cn(
                    'group relative rounded-md transition-colors border-l-2',
                    active
                      ? 'bg-accent/60 border-primary'
                      : 'border-transparent hover:bg-accent/30',
                  )}
                >
                  <Link
                    to={`/runs/${run.run_id}`}
                    className="block w-full text-left px-3 py-2.5 pr-9"
                  >
                    <div className="flex items-center gap-2 mb-0.5">
                      <StatusDot status={run.status} />
                      <span className="text-xs text-muted-foreground mono">
                        {formatElapsed(elapsedSeconds(run.started_at, run.finished_at))}
                      </span>
                      <span className="ml-auto text-xs text-muted-foreground">{run.step_count}s</span>
                    </div>
                    <p className="text-xs text-foreground truncate leading-snug">{run.task}</p>
                  </Link>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Re-run"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      openNewRun(runSummaryToDraft(run))
                    }}
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )
            })}
          </div>
        )}
      </ScrollArea>

      <div className="border-t border-border p-2 space-y-0.5">
        <NavLink to="/" icon={Home} label="Home" end />
        <NavLink to="/websites" icon={Globe} label="Websites" />
        <NavLink to="/tools" icon={Wrench} label="Tools" />
        <NavLink to="/settings" icon={Settings} label="Settings" />
      </div>
    </aside>
  )
}
