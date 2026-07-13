import type { ComponentType } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listRuns } from '@/api'
import Sidebar from '@/components/Sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'

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
      <div className="flex h-full bg-background text-foreground">
        <Sidebar runs={runs} activeRunId={activeRunId} />
        <main className="flex-1 min-w-0 overflow-hidden flex flex-col">
          <Outlet />
        </main>
      </div>
    </TooltipProvider>
  )
}

export function NavLink({
  to,
  icon: Icon,
  label,
  end = false,
}: {
  to: string
  icon: ComponentType<{ className?: string }>
  label: string
  end?: boolean
}) {
  const location = useLocation()
  const active = end ? location.pathname === to : location.pathname.startsWith(to)

  return (
    <Link
      to={to}
      className={`flex items-center gap-2.5 px-3 py-2 text-sm rounded-md transition-colors ${
        active
          ? 'bg-accent text-accent-foreground font-medium'
          : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
      }`}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label}
    </Link>
  )
}
