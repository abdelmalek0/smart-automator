import { useState } from 'react'
import type { Step, StepStatus } from '@/types'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { AlertTriangle, Check, Circle, Loader2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { actDurationMs, formatDurationMs, hasTurnTiming } from '@/lib/run-status'

interface Props {
  step: Step
  isActive?: boolean
}

function StatusIcon({ status, isActive }: { status: StepStatus; isActive: boolean }) {
  if (isActive && status === 'running')
    return <Loader2 className="w-3.5 h-3.5 text-brand-blue animate-spin" />
  if (status === 'pass') return <Check className="w-3.5 h-3.5 text-success" />
  if (status === 'fail') return <X className="w-3.5 h-3.5 text-destructive" />
  if (status === 'error') return <AlertTriangle className="w-3.5 h-3.5 text-warning" />
  return <Circle className="w-3.5 h-3.5 text-muted-foreground/50" />
}

export default function StepCard({ step, isActive = false }: Props) {
  const [imgOpen, setImgOpen] = useState(false)
  const [imgError, setImgError] = useState(false)

  const screenshotSrc = step.screenshot_url ? `${step.screenshot_url}?v=${step.index}` : null
  const isSelfHeal = step.action === 'write_tool' || step.action === 'update_tool'
  const isHuman = step.source === 'human'
  const showStepTiming = hasTurnTiming(step.turn_timing)
  const stepTiming = step.turn_timing

  const borderClass = isHuman
    ? 'border-l-warning'
    : step.status === 'pass'
      ? 'border-l-success'
      : step.status === 'error' || step.status === 'fail'
        ? 'border-l-destructive'
        : isActive
          ? 'border-l-primary'
          : 'border-l-border'

  return (
    <>
      <Accordion type="single" collapsible className="w-full">
        <AccordionItem
          value={`step-${step.index}`}
          className={cn('border rounded-lg bg-card border-l-2', borderClass)}
        >
          <AccordionTrigger className="px-4 py-2.5 hover:no-underline hover:bg-accent/30 rounded-lg [&[data-state=open]]:rounded-b-none">
            <div className="flex items-center gap-3 flex-1 min-w-0 text-left">
              <StatusIcon status={step.status} isActive={isActive} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-muted-foreground">#{step.index}</span>
                  <span className="text-sm mono font-medium">{step.action}</span>
                  {isSelfHeal && (
                    <Badge variant="outline" className="text-[10px] py-0 text-primary border-primary/30">
                      self-heal
                    </Badge>
                  )}
                  {isHuman && (
                    <Badge variant="outline" className="text-[10px] py-0 text-warning border-warning/40">
                      human
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground truncate mt-0.5">{step.thought}</p>
              </div>
              {step.elapsed_ms > 0 && (
                showStepTiming && stepTiming ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="text-xs mono text-muted-foreground shrink-0 cursor-help border-b border-dotted border-muted-foreground/60">
                        {formatDurationMs(step.elapsed_ms)}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="left" className="space-y-1">
                      <p>DOM: {formatDurationMs(stepTiming.snapshot_ms ?? 0)}</p>
                      <p>LLM: {formatDurationMs(stepTiming.llm_navigator_ms ?? 0)}</p>
                      <p>Act: {formatDurationMs(actDurationMs(stepTiming))}</p>
                      {(stepTiming.batch_ms ?? 0) > 0 && (
                        <p>Actions: {formatDurationMs(stepTiming.batch_ms ?? 0)}</p>
                      )}
                      {(stepTiming.settle_ms ?? 0) > 0 && (
                        <p>Settle: {formatDurationMs(stepTiming.settle_ms ?? 0)}</p>
                      )}
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  <span className="text-xs mono text-muted-foreground shrink-0">
                    {formatDurationMs(step.elapsed_ms)}
                  </span>
                )
              )}
            </div>
          </AccordionTrigger>
          <AccordionContent className="px-4 pb-4 space-y-3">
            <div>
              <span className="text-xs text-muted-foreground uppercase tracking-wide">Thought</span>
              <p className="text-xs text-muted-foreground italic mt-1 leading-relaxed">{step.thought}</p>
            </div>

            {Object.keys(step.args).length > 0 && (
              <div>
                <span className="text-xs text-muted-foreground uppercase tracking-wide">Args</span>
                <pre className="mt-1 text-xs mono text-cyan-400/90 bg-muted rounded-md p-2 overflow-x-auto whitespace-pre-wrap break-all">
                  {JSON.stringify(step.args, null, 2)}
                </pre>
              </div>
            )}

            {step.action === 'human_handoff' && step.args?.analysis && (
              <div>
                <span className="text-xs text-muted-foreground uppercase tracking-wide">Handoff analysis</span>
                <pre className="mt-1 text-xs mono text-warning/90 bg-warning/10 rounded-md p-2 overflow-x-auto whitespace-pre-wrap break-all">
                  {JSON.stringify(step.args.analysis, null, 2)}
                </pre>
              </div>
            )}

            {step.result && (
              <div>
                <span className="text-xs text-muted-foreground uppercase tracking-wide">Observation</span>
                <pre
                  className={cn(
                    'mt-1 text-xs mono rounded-md p-2 overflow-x-auto whitespace-pre-wrap break-all',
                    step.status === 'pass' || step.status === 'running'
                      ? 'text-success/90 bg-success/10'
                      : 'text-destructive/90 bg-destructive/10',
                  )}
                >
                  {step.result.length > 800 ? step.result.slice(0, 800) + '…' : step.result}
                </pre>
              </div>
            )}

            {screenshotSrc && !imgError && (
              <div>
                <span className="text-xs text-muted-foreground uppercase tracking-wide">Screenshot</span>
                <img
                  src={screenshotSrc}
                  alt="step screenshot"
                  onClick={() => setImgOpen(true)}
                  onError={() => setImgError(true)}
                  className="mt-1 max-w-sm rounded-md border border-border hover:border-brand-orange cursor-zoom-in transition-colors"
                />
              </div>
            )}
            {screenshotSrc && imgError && (
              <p className="text-xs text-muted-foreground italic">Screenshot unavailable.</p>
            )}
          </AccordionContent>
        </AccordionItem>
      </Accordion>

      <Dialog open={imgOpen} onOpenChange={setImgOpen}>
        <DialogContent className="max-w-4xl p-2 bg-background/95">
          {screenshotSrc && (
            <img src={screenshotSrc} alt="screenshot" className="max-w-full max-h-[80vh] rounded-md mx-auto" />
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
