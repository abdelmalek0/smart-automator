import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Globe, Loader2 } from 'lucide-react'
import { cancelRun, listWebsites } from '@/api'
import { useRunStream } from '@/hooks/useRunStream'
import RunStats from '@/components/RunStats'
import StepCard from '@/components/StepCard'
import CompletedStepsPanel from '@/components/CompletedStepsPanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { RunStatus } from '@/types'
import { statusBadgeVariant, statusLabel } from '@/lib/run-status'

interface Props {
  runId: string
  onRunComplete?: () => void
}

export default function RunView({ runId, onRunComplete }: Props) {
  const {
    run,
    connected,
    closed,
    error: streamError,
    reportReady,
  } = useRunStream(runId)
  const bottomRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const { data: websites = [] } = useQuery({
    queryKey: ['websites'],
    queryFn: listWebsites,
    staleTime: 60_000,
  })
  const websiteName = run?.website_id
    ? websites.find((w) => w.id === run.website_id)?.name
    : null

  useEffect(() => {
    if (run?.status === 'running') {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [run?.steps.length, run?.status])

  useEffect(() => {
    if (closed || (run && run.status !== 'running' && run.status !== 'pending')) {
      onRunComplete?.()
      queryClient.invalidateQueries({ queryKey: ['runs'] })
    }
  }, [closed, run?.status, onRunComplete, queryClient])

  const isRunning = run?.status === 'running' || run?.status === 'pending'
  const showReport =
    reportReady || (run?.status && ['pass', 'fail', 'error'].includes(run.status))

  async function handleCancel() {
    try {
      await cancelRun(runId)
      queryClient.invalidateQueries({ queryKey: ['runs'] })
    } catch {
      // ignore
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 px-6 py-4 border-b border-border flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-xs text-muted-foreground mono mb-1">{runId.slice(0, 8)}</p>
          {websiteName && (
            <Badge variant="outline" className="mb-1.5 text-[10px] gap-1">
              <Globe className="h-3 w-3" />
              {websiteName}
            </Badge>
          )}
          <h2 className="text-sm font-medium leading-snug line-clamp-5">{run?.task ?? '…'}</h2>
          {streamError && run?.status === 'error' && (
            <p className="mt-1 text-xs text-destructive break-words">{streamError}</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">
          {run && (
            <Badge variant={statusBadgeVariant(run.status as RunStatus)}>
              {isRunning && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
              {statusLabel(run.status as RunStatus)}
            </Badge>
          )}
          {isRunning && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" size="sm" className="text-destructive border-destructive/30">
                  Cancel
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Cancel this run?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The agent will stop executing. This cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep running</AlertDialogCancel>
                  <AlertDialogAction onClick={handleCancel}>Cancel run</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
          {showReport && (
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/runs/${runId}/report`} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-3.5 w-3.5" />
                Report
              </a>
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="flex-shrink-0 px-5 py-3 border-b border-border space-y-3">
          {!connected && !closed && run === null && (
            <p className="text-xs text-muted-foreground flex items-center gap-2">
              <Loader2 className="h-3 w-3 animate-spin" />
              Connecting…
            </p>
          )}
          <div className="flex flex-row gap-3 items-stretch">
            <CompletedStepsPanel steps={run?.steps} isRunning={isRunning} />
            <RunStats
              stepCount={run?.steps.length}
              status={run?.status}
              elapsedS={run ? Date.now() / 1000 - run.started_at : undefined}
              tokens={run?.tokens}
              promptTokens={run?.prompt_tokens}
              completionTokens={run?.completion_tokens}
              cacheTokens={run?.cache_tokens}
              costUsd={run?.cost_usd}
              turnTiming={run?.turn_timing}
            />
          </div>
        </div>

        <ScrollArea className="flex-1 px-5 py-4">
          <div className="space-y-2 max-w-4xl">
            {run && run.new_tools.length > 0 && (
              <div className="border border-primary/25 rounded-lg px-4 py-2 bg-primary/5">
                <p className="text-xs text-primary">
                  <strong>Self-healed:</strong> Agent extended its toolset:{' '}
                  {run.new_tools.map((t) => (
                    <code key={t} className="mono px-1 rounded bg-muted">
                      {t}()
                    </code>
                  ))}
                </p>
              </div>
            )}

            {run?.steps.map((step, i) => (
              <StepCard
                key={step.index}
                step={step}
                isActive={i === run.steps.length - 1 && isRunning}
              />
            ))}

            {run?.summary && !isRunning && (
              <div
                className={`rounded-lg px-4 py-3 border text-sm ${
                  run.status === 'pass'
                    ? 'bg-success/10 border-success/30 text-success'
                    : 'bg-destructive/10 border-destructive/30 text-destructive'
                }`}
              >
                <strong>Summary:</strong> {run.summary}
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
