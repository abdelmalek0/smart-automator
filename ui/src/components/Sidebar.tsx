import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import logoUrl from '../../logo.jpeg'
import type { RunSummary } from '@/types'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useRunModal } from '@/contexts/RunModalContext'
import RunThreadList from '@/components/RunThreadList'
import SidebarNav from '@/components/SidebarNav'
import { useWebsites } from '@/hooks/useWebsites'

interface Props {
  runs: RunSummary[]
  activeRunId: string | null
}

export default function Sidebar({ runs, activeRunId }: Props) {
  const { openNewRun } = useRunModal()
  const { websites } = useWebsites()
  const websiteNames = useMemo(
    () => Object.fromEntries(websites.map((website) => [website.id, website.name])),
    [websites],
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
            websiteNames={websiteNames}
          />
        </div>
      </ScrollArea>

      <SidebarNav />
    </aside>
  )
}
