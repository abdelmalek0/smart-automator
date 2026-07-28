import { Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listRuns } from '@/api'
import Sidebar from '@/components/Sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { RunModalProvider } from '@/contexts/RunModalContext'

export default function AppShell() {
  const location = useLocation()
  const { data: runs = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: listRuns,
    refetchInterval: 3000,
  })

  const activeRunId = location.pathname.startsWith('/runs/')
    ? location.pathname.split('/')[2] ?? null
    : null

  return (
    <TooltipProvider delayDuration={200}>
      <RunModalProvider>
        <div className="flex h-full bg-background text-foreground">
          <Sidebar runs={runs} activeRunId={activeRunId} />
          <main className="flex-1 min-w-0 overflow-hidden flex flex-col">
            <Outlet />
          </main>
        </div>
      </RunModalProvider>
    </TooltipProvider>
  )
}
