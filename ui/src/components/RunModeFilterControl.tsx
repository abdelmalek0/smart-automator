import { cn } from '@/lib/utils'
import { RUN_MODE_FILTERS, type RunModeFilter } from '@/lib/run-threads'

interface Props {
  value: RunModeFilter
  onChange: (value: RunModeFilter) => void
  /** Compact for sidebar; default for home. */
  size?: 'sm' | 'md'
  className?: string
}

export default function RunModeFilterControl({
  value,
  onChange,
  size = 'sm',
  className,
}: Props) {
  return (
    <div
      className={cn(
        'grid grid-cols-3 gap-0.5 rounded-md border border-border/70 bg-muted/40 p-0.5',
        className,
      )}
      role="group"
      aria-label="Filter by run mode"
    >
      {RUN_MODE_FILTERS.map((option) => {
        const selected = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={cn(
              'rounded-[5px] font-medium transition-colors',
              size === 'sm' ? 'px-1.5 py-1 text-[10px]' : 'px-2.5 py-1.5 text-xs',
              selected
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
            aria-pressed={selected}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
