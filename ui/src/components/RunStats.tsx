import { Card, CardContent } from '@/components/ui/card'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Loader2 } from 'lucide-react'
import {
  actDurationMs,
  aggregateTypicalActMs,
  formatDurationMs,
  hasTurnTiming,
} from '@/lib/run-status'
import type { CostBreakdownEntry, Step, TurnTiming } from '@/types'

interface Props {
  stepCount?: number
  status?: string
  elapsedS?: number
  tokens?: number
  promptTokens?: number
  completionTokens?: number
  cacheTokens?: number
  costUsd?: number | null
  costBreakdown?: CostBreakdownEntry[]
  steps?: Step[]
  typicalTiming?: TurnTiming | null
  currentTiming?: TurnTiming
}

export default function RunStats({
  stepCount,
  status,
  elapsedS,
  tokens,
  promptTokens,
  completionTokens,
  cacheTokens,
  costUsd,
  costBreakdown,
  steps,
  typicalTiming,
  currentTiming,
}: Props) {
  const isRunning = status === 'running' || status === 'pending'

  const elapsed =
    elapsedS !== undefined
      ? elapsedS < 60
        ? `${Math.round(elapsedS)}s`
        : `${Math.floor(elapsedS / 60)}m ${Math.round(elapsedS % 60)}s`
      : null

  const showTypicalTiming = hasTurnTiming(typicalTiming)
  const typicalActMs =
    steps && steps.length > 0 ? aggregateTypicalActMs(steps) : actDurationMs(typicalTiming ?? {})

  const showCurrentTiming = isRunning && hasTurnTiming(currentTiming)
  const currentActMs = currentTiming ? actDurationMs(currentTiming) : 0

  const showCostBreakdown =
    (costBreakdown?.length ?? 0) > 1 &&
    new Set(costBreakdown!.map((entry) => `${entry.provider}/${entry.model}`)).size > 1

  const costLabel =
    costUsd === null || costUsd === undefined
      ? '—'
      : costUsd === 0
        ? 'free'
        : `$${costUsd.toFixed(4)}`

  return (
    <Card className="flex-[1] min-w-[10rem]">
      <CardContent className="p-4 space-y-2">
        <StatRow label="Status">
          {isRunning ? (
            <span className="flex items-center gap-1.5 text-xs text-brand-blue">
              <Loader2 className="w-3 h-3 animate-spin" />
              Running
            </span>
          ) : status === 'pass' ? (
            <span className="text-xs text-success">Pass</span>
          ) : status === 'fail' ? (
            <span className="text-xs text-destructive">Fail</span>
          ) : status === 'error' ? (
            <span className="text-xs text-warning">Error</span>
          ) : status === 'cancelled' ? (
            <span className="text-xs text-muted-foreground">Cancelled</span>
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          )}
        </StatRow>
        {stepCount !== undefined && (
          <StatRow label="Steps">
            <span className="text-xs mono">{stepCount}</span>
          </StatRow>
        )}
        {tokens !== undefined && tokens > 0 && (
          <StatRow label="Tokens">
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-xs mono cursor-help border-b border-dotted border-muted-foreground">
                  {tokens.toLocaleString()}
                </span>
              </TooltipTrigger>
              <TooltipContent side="left" className="space-y-1">
                <p>Input tokens: {(promptTokens ?? 0).toLocaleString()}</p>
                <p>Output tokens: {(completionTokens ?? 0).toLocaleString()}</p>
                {(cacheTokens ?? 0) > 0 && (
                  <p>Cache tokens: {(cacheTokens ?? 0).toLocaleString()}</p>
                )}
              </TooltipContent>
            </Tooltip>
          </StatRow>
        )}
        {tokens !== undefined && tokens > 0 && (
          <StatRow label="Cost">
            {showCostBreakdown ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="text-xs mono cursor-help border-b border-dotted border-muted-foreground">
                    {costLabel}
                  </span>
                </TooltipTrigger>
                <TooltipContent side="left" className="space-y-1">
                  {costBreakdown!.map((entry) => (
                    <p key={`${entry.role}-${entry.provider}-${entry.model}`}>
                      {formatCostRole(entry.role)} ({entry.provider}/{entry.model}):{' '}
                      {formatCostUsd(entry.cost_usd)}
                    </p>
                  ))}
                </TooltipContent>
              </Tooltip>
            ) : (
              <span className="text-xs mono">{costLabel}</span>
            )}
          </StatRow>
        )}
        {elapsed && (
          <StatRow label="Total time">
            <span className="text-xs mono">{elapsed}</span>
          </StatRow>
        )}
        {showTypicalTiming && typicalTiming && (
          <TurnTimingRow
            label="Typical turn"
            timing={typicalTiming}
            actMs={typicalActMs}
          />
        )}
        {showCurrentTiming && currentTiming && (
          <TurnTimingRow
            label="Current"
            timing={currentTiming}
            actMs={currentActMs}
            muted
          />
        )}
      </CardContent>
    </Card>
  )
}

function TurnTimingRow({
  label,
  timing,
  actMs,
  muted = false,
}: {
  label: string
  timing: TurnTiming
  actMs: number
  muted?: boolean
}) {
  return (
    <StatRow label={label}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={`text-xs mono cursor-help border-b border-dotted border-muted-foreground${muted ? ' text-muted-foreground' : ''}`}
          >
            {formatDurationMs(timing.turn_ms ?? 0)}
          </span>
        </TooltipTrigger>
        <TooltipContent side="left" className="space-y-1">
          <p>DOM: {formatDurationMs(timing.snapshot_ms ?? 0)}</p>
          <p>LLM: {formatDurationMs(timing.llm_navigator_ms ?? 0)}</p>
          <p>Act: {formatDurationMs(actMs)}</p>
          {(timing.batch_ms ?? 0) > 0 && (
            <p>Actions: {formatDurationMs(timing.batch_ms ?? 0)}</p>
          )}
          {(timing.settle_ms ?? 0) > 0 && (
            <p>Settle: {formatDurationMs(timing.settle_ms ?? 0)}</p>
          )}
        </TooltipContent>
      </Tooltip>
    </StatRow>
  )
}

function formatCostRole(role: string): string {
  if (role === 'navigation') return 'Navigation'
  if (role === 'planning') return 'Planning'
  return role
}

function formatCostUsd(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return '—'
  if (cost === 0) return 'free'
  return `$${cost.toFixed(4)}`
}

function StatRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}
