import { Card, CardContent } from '@/components/ui/card'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Loader2 } from 'lucide-react'
import { actDurationMs, formatDurationMs, hasTurnTiming } from '@/lib/run-status'
import type { TurnTiming } from '@/types'

interface Props {
  stepCount?: number
  status?: string
  elapsedS?: number
  tokens?: number
  promptTokens?: number
  completionTokens?: number
  cacheTokens?: number
  costUsd?: number | null
  turnTiming?: TurnTiming
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
  turnTiming,
}: Props) {
  const isRunning = status === 'running' || status === 'pending'

  const elapsed =
    elapsedS !== undefined
      ? elapsedS < 60
        ? `${Math.round(elapsedS)}s`
        : `${Math.floor(elapsedS / 60)}m ${Math.round(elapsedS % 60)}s`
      : null

  const showTurnTiming = hasTurnTiming(turnTiming)
  const actMs = turnTiming ? actDurationMs(turnTiming) : 0

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
            <span className="text-xs mono">
              {costUsd === null || costUsd === undefined
                ? '—'
                : costUsd === 0
                  ? 'free'
                  : `$${costUsd.toFixed(4)}`}
            </span>
          </StatRow>
        )}
        {elapsed && (
          <StatRow label="Total time">
            <span className="text-xs mono">{elapsed}</span>
          </StatRow>
        )}
        {showTurnTiming && turnTiming && (
          <StatRow label="Last turn">
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-xs mono cursor-help border-b border-dotted border-muted-foreground">
                  {formatDurationMs(turnTiming.turn_ms ?? 0)}
                </span>
              </TooltipTrigger>
              <TooltipContent side="left" className="space-y-1">
                <p>DOM: {formatDurationMs(turnTiming.snapshot_ms ?? 0)}</p>
                <p>LLM: {formatDurationMs(turnTiming.llm_navigator_ms ?? 0)}</p>
                <p>Act: {formatDurationMs(actMs)}</p>
                {(turnTiming.batch_ms ?? 0) > 0 && (
                  <p>Actions: {formatDurationMs(turnTiming.batch_ms ?? 0)}</p>
                )}
                {(turnTiming.settle_ms ?? 0) > 0 && (
                  <p>Settle: {formatDurationMs(turnTiming.settle_ms ?? 0)}</p>
                )}
              </TooltipContent>
            </Tooltip>
          </StatRow>
        )}
      </CardContent>
    </Card>
  )
}

function StatRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}
