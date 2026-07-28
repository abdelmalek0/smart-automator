import type { ComponentType } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Globe, Home, Settings } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
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
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          to={to}
          aria-label={label}
          className={cn(
            'flex flex-1 items-center justify-center rounded-md py-2 transition-colors',
            active
              ? 'bg-accent/60 text-primary'
              : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground',
          )}
        >
          <Icon className="h-4 w-4" />
        </Link>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  )
}

export default function SidebarNav() {
  return (
    <nav className="flex items-center gap-1 px-2 py-2 border-t border-border/60">
      <NavItem to="/" icon={Home} label="Home" end />
      <NavItem to="/websites" icon={Globe} label="Projects" />
      <NavItem to="/settings" icon={Settings} label="Settings" />
    </nav>
  )
}
