import type { ComponentType } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Globe, Home, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'

interface NavItemProps {
  to: string
  icon: ComponentType<{ className?: string }>
  label: string
  end?: boolean
}

function NavItem({ to, icon: Icon, label, end = false }: NavItemProps) {
  const location = useLocation()
  const active = end ? location.pathname === to : location.pathname.startsWith(to)

  return (
    <Link
      to={to}
      className={cn(
        'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
        active
          ? 'bg-accent/60 text-primary'
          : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground',
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{label}</span>
    </Link>
  )
}

export default function SidebarNav() {
  return (
    <nav className="flex flex-col gap-0.5 px-2 py-2">
      <NavItem to="/" icon={Home} label="Home" end />
      <NavItem to="/projects" icon={Globe} label="Projects" />
      <NavItem to="/settings" icon={Settings} label="Settings" />
    </nav>
  )
}
