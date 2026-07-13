import type { AtomicStep } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Check, Circle, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  extractedSteps?: AtomicStep[]
  currentStep?: number | null
  atomicProgress?: {
    current?: number | null
    total?: number
    completed?: number
    validated?: number
  }
  screenSummary?: string
}

const actionColors: Record<AtomicStep['action'], string> = {
  navigate: 'text-brand-blue',
  interact: 'text-primary',
  choose: 'text-warning',
  assert: 'text-success',
}

export default function AtomicProgressPanel({
  extractedSteps = [],
  currentStep,
  atomicProgress,
  screenSummary,
}: Props) {
  const total = atomicProgress?.total ?? extractedSteps.length
  const completed = atomicProgress?.completed ?? 0
  const activeStep = atomicProgress?.current ?? currentStep ?? null
  const hasSteps = extractedSteps.length > 0
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0

  return (
    <Card className="flex-[2] min-w-0">
      <CardHeader className="py-3 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Atomic Steps
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
        {screenSummary && (
          <p className="text-xs text-muted-foreground mb-3 leading-relaxed border-l-2 border-primary/40 pl-3">
            {screenSummary}
          </p>
        )}
        {hasSteps ? (
          <ScrollArea className="max-h-24">
            <div className="space-y-1.5">
              {extractedSteps.map((step) => {
                const isCurrent = activeStep === step.step
                const isPast = completed > 0 && step.step <= completed && !isCurrent
                return (
                  <div
                    key={step.step}
                    className={cn(
                      'flex items-start gap-2 text-xs',
                      isCurrent && 'text-foreground',
                      !isCurrent && !isPast && 'text-muted-foreground',
                      isPast && 'text-muted-foreground/80',
                    )}
                  >
                    <span className="mt-0.5 flex-shrink-0">
                      {isCurrent ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-brand-blue" />
                      ) : isPast ? (
                        <Check className="h-3.5 w-3.5 text-success" />
                      ) : (
                        <Circle className="h-3.5 w-3.5 text-muted-foreground/50" />
                      )}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="mono text-muted-foreground">#{step.step}</span>
                        <Badge
                          variant="outline"
                          className={cn('text-[10px] py-0', actionColors[step.action])}
                        >
                          {step.action}
                        </Badge>
                        <span className="leading-snug">{step.target}</span>
                      </div>
                      {step.value && (
                        <span className="mono text-muted-foreground block mt-0.5 leading-snug">
                          → {step.value}
                        </span>
                      )}
                      {step.note && (
                        <span className="text-muted-foreground/80 block mt-0.5 leading-snug italic">
                          {step.note}
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
            Waiting for task breakdown…
          </p>
        )}
      </CardContent>
    </Card>
  )
}
