import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { LogOut, Plus } from 'lucide-react'
import logoUrl from '../../logo.jpeg'
import type { RunSummary } from '@/types'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useRunModal } from '@/contexts/RunModalContext'
import { useAuth } from '@/contexts/AuthContext'
import RunThreadList from '@/components/RunThreadList'
import SidebarNav from '@/components/SidebarNav'
import { useProjects } from '@/hooks/useProjects'

interface Props {
  runs: RunSummary[]
  activeRunId: string | null
}

export default function Sidebar({ runs, activeRunId }: Props) {
  const { openNewRun } = useRunModal()
  const { user, logout } = useAuth()
  const { projects } = useProjects()
  const projectNames = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project.name])),
    [projects],
  )

  return (
    <aside className="w-[260px] flex-shrink-0 bg-card/80 backdrop-blur-sm border-r border-border/60 flex flex-col h-full">
      <div className="px-3 py-3 bg-secondary/30">
        <Link
          to="/"
          title="Smart Automator — Browser Agent"
          className="flex items-center gap-2 mb-3 hover:opacity-90 transition-opacity"
        >
          <img
            src={logoUrl}
            alt="Smart Automator"
            className="w-7 h-7 rounded-md object-cover flex-shrink-0 ring-1 ring-border/60"
          />
          <span className="font-semibold text-sm tracking-tight truncate">Smart Automator</span>
        </Link>
        <Button onClick={() => openNewRun()} className="w-full h-9" size="sm">
          <Plus className="h-4 w-4" />
          New Run
        </Button>
      </div>

      <div className="px-3 pt-3 pb-1.5">
        <span className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          Recent
        </span>
      </div>

      <ScrollArea className="flex-1 px-1.5">
        <div className="pb-2">
          <RunThreadList
            runs={runs}
            activeRunId={activeRunId}
            variant="sidebar"
            projectNames={projectNames}
            projects={projects}
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
