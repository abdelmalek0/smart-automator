import type { ReactNode } from 'react'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export default function SettingsRow({
  label,
  hint,
  htmlFor,
  stacked = false,
  children,
}: {
  label: ReactNode
  hint?: string
  htmlFor?: string
  stacked?: boolean
  children: ReactNode
}) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 gap-x-8 gap-y-2 items-start py-4 first:pt-0 last:pb-0 border-b border-border/40 last:border-0',
        !stacked && 'sm:grid-cols-[9.5rem_1fr]',
      )}
    >
      <Label htmlFor={htmlFor} className={cn('text-sm font-medium text-foreground/90', !stacked && 'sm:pt-2')}>
        {label}
      </Label>
      <div className="min-w-0">
        {children}
        {hint && (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">{hint}</p>
        )}
      </div>
    </div>
  )
}
