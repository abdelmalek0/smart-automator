import type { Step, StepStatus } from '@/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { AlertTriangle, Check, Circle, Loader2, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  steps?: Step[]
  isRunning?: boolean
}

function StepIcon({
  status,
  isActive,
  isHuman = false,
}: {
  status: StepStatus
  isActive: boolean
  isHuman?: boolean
}) {
  if (isHuman) {
    return <Circle className="h-3.5 w-3.5 text-warning" />
  }
  if (isActive && status === 'running') {
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-brand-blue" />
  }
  if (status === 'pass') return <Check className="h-3.5 w-3.5 text-success" />
  if (status === 'fail') return <X className="h-3.5 w-3.5 text-destructive" />
  if (status === 'error') return <AlertTriangle className="h-3.5 w-3.5 text-warning" />
  return <Circle className="h-3.5 w-3.5 text-muted-foreground/50" />
}

function isFinished(status: StepStatus): boolean {
  return status === 'pass' || status === 'fail' || status === 'error'
}

export default function CompletedStepsPanel({ steps = [], isRunning = false }: Props) {
  const total = steps.length
  const completed = steps.filter((step) => isFinished(step.status)).length
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0
  const activeIndex = isRunning && total > 0 ? steps[total - 1]?.index : null

  return (
    <Card className="flex-[2] min-w-0">
      <CardHeader className="py-3 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Completed Steps
          </CardTitle>
          {total > 0 && (
            <span className="text-xs mono text-primary">
              {completed}/{total}
            </span>
          )}
        </div>
        {total > 0 && (
          <div className="w-full bg-muted rounded-full h-1 mt-2">
            <div
              className="h-1 rounded-full bg-primary transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
        )}
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        {total > 0 ? (
          <ScrollArea className="max-h-24">
            <div className="space-y-1.5">
              {steps.map((step) => {
                const isActive = activeIndex === step.index
                const isPast = isFinished(step.status) && !isActive
                return (
                  <div
                    key={`${step.index}-${step.source ?? 'agent'}`}
                    className={cn(
                      'flex items-start gap-2 text-xs',
                      isActive && 'text-foreground',
                      !isActive && !isPast && 'text-muted-foreground',
                      isPast && 'text-muted-foreground/80',
                    )}
                  >
                    <span className="mt-0.5 flex-shrink-0">
                      <StepIcon status={step.status} isActive={isActive} isHuman={step.source === 'human'} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="mono text-muted-foreground">#{step.index}</span>
                        <span className={cn('mono font-medium', step.source === 'human' && 'text-warning')}>
                          {step.action}
                        </span>
                      </div>
                      {step.thought && (
                        <span className="text-muted-foreground block mt-0.5 leading-snug line-clamp-2">
                          {step.thought}
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </ScrollArea>
        ) : (
          <p className="text-xs text-muted-foreground italic">
            {isRunning ? 'Waiting for first step…' : 'No steps yet'}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
