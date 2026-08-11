import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, LogOut, Plus } from 'lucide-react'
import logoUrl from '../../logo.jpeg'
import type { RunSummary } from '@/types'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useRunModal } from '@/contexts/RunModalContext'
import { useAuth } from '@/contexts/AuthContext'
import RunModeFilterControl from '@/components/RunModeFilterControl'
import AgentStatusStrip from '@/components/AgentStatusStrip'
import RunThreadList from '@/components/RunThreadList'
import SidebarNav from '@/components/SidebarNav'
import { useRunStartGate } from '@/hooks/useRunStartGate'
import { useProjects } from '@/hooks/useProjects'
import { cn } from '@/lib/utils'
import type { RunModeFilter } from '@/lib/run-threads'

interface Props {
  runs: RunSummary[]
  activeRunId: string | null
}

export default function Sidebar({ runs, activeRunId }: Props) {
  const [recentExpanded, setRecentExpanded] = useState(true)
  const [expandAllToken, setExpandAllToken] = useState(0)
  const [modeFilter, setModeFilter] = useState<RunModeFilter>('all')
  const { openNewRun } = useRunModal()
  const runStartGate = useRunStartGate()
  const { user, logout } = useAuth()
  const { projects } = useProjects()
  const projectNames = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project.name])),
    [projects],
  )

  return (
    <aside className="w-[300px] flex-shrink-0 bg-card/80 backdrop-blur-sm border-r border-border/60 flex flex-col h-full">
      <div className="bg-secondary/30 border-b border-border/40">
        <Link
          to="/"
          title="Smart Automator — Browser Agent"
          className="flex items-center gap-2.5 px-3 pt-4 pb-3 min-w-0 hover:opacity-90 transition-opacity"
        >
          <img
            src={logoUrl}
            alt="Smart Automator"
            className="w-8 h-8 rounded-md object-cover flex-shrink-0 ring-1 ring-border/60"
          />
          <span className="font-semibold text-sm tracking-tight truncate">Smart Automator</span>
        </Link>

        <div className="border-t border-border/40 px-3 pt-3 pb-3 space-y-2">
          <AgentStatusStrip embedded />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full h-8 text-muted-foreground"
            title={runStartGate.blockHint ?? 'New run'}
            disabled={!runStartGate.canStartRun}
            onClick={() => openNewRun()}
          >
            <Plus className="h-3.5 w-3.5" />
            New run
          </Button>
        </div>
      </div>

      <button
        type="button"
        onClick={() => {
          setRecentExpanded((prev) => {
            if (!prev) setExpandAllToken((token) => token + 1)
            return !prev
          })
        }}
        className={cn(
          'flex w-full items-center justify-between gap-2 px-3 pt-3 pb-1.5 text-left transition-colors rounded-md',
          'hover:bg-accent/30',
        )}
        title={recentExpanded ? 'Collapse to project names' : 'Expand recent runs'}
        aria-expanded={recentExpanded}
      >
        <span className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          Recent
        </span>
        {recentExpanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
        )}
      </button>

      {recentExpanded ? (
        <div className="px-3 pb-2">
          <RunModeFilterControl value={modeFilter} onChange={setModeFilter} size="sm" />
        </div>
      ) : null}

      <ScrollArea className="flex-1 px-1.5">
        <div className="pb-2">
          <RunThreadList
            runs={runs}
            activeRunId={activeRunId}
            variant="sidebar"
            projectNames={projectNames}
            projects={projects}
            modeFilter={modeFilter}
            rootsCollapsed={!recentExpanded}
            expandAllToken={expandAllToken}
            onRequestExpandRoots={() => setRecentExpanded(true)}
          />
        </div>
      </ScrollArea>

      <footer className="border-t border-border/60">
        <SidebarNav />

        {user ? (
          <div className="flex items-center gap-2 px-3 py-2.5 border-t border-border/60">
            <div
              aria-hidden
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary"
            >
              {user.username.charAt(0).toUpperCase()}
            </div>
            <p className="min-w-0 flex-1 text-xs font-medium truncate">{user.username}</p>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
              title="Sign out"
              onClick={() => void logout()}
            >
              <LogOut className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : null}
      </footer>
    </aside>
  )
}
