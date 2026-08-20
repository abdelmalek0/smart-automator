import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Globe, Hand, Loader2, RotateCcw } from 'lucide-react'
import { cancelRun, finishManual, listProjects, listRuns, returnControl, takeControl } from '@/api'
import { useRunStream } from '@/hooks/useRunStream'
import RunStats from '@/components/RunStats'
import StepCard from '@/components/StepCard'
import CompletedStepsPanel from '@/components/CompletedStepsPanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useRunModal } from '@/contexts/RunModalContext'
import { getPrimaryRunAction } from '@/lib/run-draft'
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
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { RunStatus } from '@/types'
import {
  aggregateTurnTiming,
  elapsedSeconds,
  executionModeChipClass,
  executionModeLabel,
  executionModeShortLabel,
  isManualRun,
  MANUAL_PLACEHOLDER_TASK,
  runModeOf,
  statusBadgeVariant,
  statusLabel,
} from '@/lib/run-status'

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
  const { openNewRun } = useRunModal()
  const [hitlCountdown, setHitlCountdown] = useState<string | null>(null)
  const [hitlBusy, setHitlBusy] = useState(false)
  const [takeControlPending, setTakeControlPending] = useState(false)
  const [hitlError, setHitlError] = useState<string | null>(null)
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
    staleTime: 60_000,
  })
  const { data: allRuns = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: listRuns,
    staleTime: 30_000,
  })
  const projectName = run?.website_id
    ? projects.find((p) => p.id === run.website_id)?.name
    : null
  const sourceRunExists = Boolean(
    run?.source_run_id && allRuns.some((item) => item.run_id === run.source_run_id),
  )

  useEffect(() => {
    if (run?.status === 'running' || run?.status === 'awaiting_human') {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [run?.steps.length, run?.status])

  useEffect(() => {
    if (!run?.hitl_deadline || run.status !== 'awaiting_human') {
      setHitlCountdown(null)
      return
    }
    const update = () => {
      const remaining = Math.max(0, Math.floor(run.hitl_deadline! - Date.now() / 1000))
      const minutes = Math.floor(remaining / 60)
      const seconds = remaining % 60
      setHitlCountdown(`${minutes}:${seconds.toString().padStart(2, '0')}`)
    }
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [run?.hitl_deadline, run?.status])

  useEffect(() => {
    const isTerminal =
      run?.status === 'pass' ||
      run?.status === 'fail' ||
      run?.status === 'error' ||
      run?.status === 'cancelled'
    if (closed || isTerminal) {
      onRunComplete?.()
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['workerStatus'] })
    }
  }, [closed, run?.status, onRunComplete, queryClient])

  const isActiveRun =
    run?.status === 'running' ||
    run?.status === 'pending' ||
    run?.status === 'awaiting_human'
  const isRunning = isActiveRun
  const primaryAction = run && !isActiveRun ? getPrimaryRunAction(run, projects) : null
  const humanControlling = Boolean(run?.human_controlling)
  const isManual = Boolean(run && isManualRun(run))
  const isReplay = Boolean(run && runModeOf(run) === 'automatic')
  const canUseHitl = Boolean(
    run && !run.headless && isActiveRun && !run.use_replay_script && !isManual,
  )
  const showReport =
    reportReady || (run?.status && ['pass', 'fail', 'error'].includes(run.status))

  useEffect(() => {
    if (humanControlling) {
      setTakeControlPending(false)
    }
  }, [humanControlling])

  async function handleCancel() {
    try {
      await cancelRun(runId)
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['workerStatus'] })
    } catch {
      // ignore
    }
  }

  async function handleTakeControl() {
    setHitlBusy(true)
    setHitlError(null)
    setTakeControlPending(true)
    try {
      await takeControl(runId)
    } catch (err) {
      setTakeControlPending(false)
      setHitlError(err instanceof Error ? err.message : 'Failed to take control')
    } finally {
      setHitlBusy(false)
    }
  }

  async function handleReturnControl() {
    setHitlBusy(true)
    setHitlError(null)
    try {
      await returnControl(runId)
    } catch (err) {
      setHitlError(err instanceof Error ? err.message : 'Failed to return control')
    } finally {
      setHitlBusy(false)
    }
  }

  async function handleFinishManual() {
    setHitlBusy(true)
    setHitlError(null)
    try {
      await finishManual(runId)
    } catch (err) {
      setHitlError(err instanceof Error ? err.message : 'Failed to finish demonstration')
    } finally {
      setHitlBusy(false)
    }
  }

  const procedureTask =
    run?.task && run.task !== MANUAL_PLACEHOLDER_TASK ? run.task : ''
  const displayTitle =
    run?.name?.trim() ||
    (isManual && isActiveRun && !procedureTask ? 'Recording demonstration…' : '') ||
    (procedureTask ? 'Untitled test' : run?.task || '…')
  const draftTask = (run?.steps ?? [])
    .filter((step) => step.source === 'human')
    .map((step, index) => `${index + 1}. ${step.result || step.action}`)
    .join('\n')
  const sourceRunId = run?.use_replay_script ? run.source_run_id : null

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 px-6 py-4 border-b border-border flex items-start gap-4">
        <div className="flex-1 min-w-0 space-y-2.5">
          <div className="space-y-1">
            <div className="flex items-center gap-2 min-w-0 flex-wrap">
              <h2 className="text-base font-semibold leading-tight truncate">{displayTitle}</h2>
              {run && (
                <span
                  title={executionModeLabel(run)}
                  className={cn(
                    'inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold shrink-0',
                    executionModeChipClass(run),
                  )}
                >
                  {executionModeShortLabel(run)}
                </span>
              )}
            </div>
            <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground flex-wrap">
              {projectName && (
                <>
                  <Globe className="h-3 w-3 shrink-0" />
                  <span className="truncate max-w-[14rem]">{projectName}</span>
                  <span aria-hidden className="text-muted-foreground/40">
                    ·
                  </span>
                </>
              )}
              <span className="mono">{runId.slice(0, 8)}</span>
              {sourceRunId && (
                <>
                  <span aria-hidden className="text-muted-foreground/40">
                    ·
                  </span>
                  {sourceRunExists ? (
                    <span>
                      from{' '}
                      <Link
                        to={`/runs/${sourceRunId}`}
                        className="mono text-primary hover:underline underline-offset-2"
                      >
                        {sourceRunId.slice(0, 8)}
                      </Link>
                    </span>
                  ) : (
                    <span>source removed</span>
                  )}
                </>
              )}
            </p>
          </div>

          {run?.success_criteria && (
            <div className="max-w-2xl">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Goal
              </p>
              <p className="mt-0.5 text-sm leading-snug">{run.success_criteria}</p>
            </div>
          )}

          {procedureTask && (
            <Accordion type="single" collapsible className="max-w-2xl">
              <AccordionItem value="test-description" className="border-none">
                <AccordionTrigger className="py-0 text-xs font-medium text-muted-foreground hover:no-underline hover:text-foreground justify-start gap-1.5 w-fit">
                  Description
                </AccordionTrigger>
                <AccordionContent className="text-xs text-muted-foreground leading-relaxed max-h-56 overflow-y-auto pt-1.5">
                  <p className="whitespace-pre-wrap">{procedureTask}</p>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          {isManual && isActiveRun && (
            <p className="text-xs text-muted-foreground">
              Perform the flow in the browser, then click Done. The agent is recording, not driving.
            </p>
          )}
          {isManual && draftTask && run?.task === MANUAL_PLACEHOLDER_TASK && (
            <p className="text-xs text-muted-foreground whitespace-pre-wrap line-clamp-6">
              <span className="font-medium text-foreground">Draft:</span> {draftTask}
            </p>
          )}
          {streamError && run?.status === 'error' && (
            <p className="text-xs text-destructive break-words">{streamError}</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">
          {run && run.status !== 'awaiting_human' && (
            <Badge
              variant={statusBadgeVariant(run.status as RunStatus)}
              className={cn(run.status === 'running' && 'gap-1.5')}
            >
              {run.status === 'running' && (
                <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
              )}
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
          {isManual && isActiveRun && (
            <div className="flex flex-col items-end gap-1">
              {hitlError && (
                <p className="text-xs text-destructive break-words max-w-[14rem] text-right">{hitlError}</p>
              )}
              <Button size="sm" onClick={handleFinishManual} disabled={hitlBusy}>
                {hitlBusy ? 'Finishing…' : 'Done'}
              </Button>
            </div>
          )}
          {canUseHitl && (
            <div className="flex flex-col items-end gap-1">
              {run?.hitl_reason && (humanControlling || run.status === 'awaiting_human') && (
                <p className="text-xs text-muted-foreground max-w-[14rem] text-right">{run.hitl_reason}</p>
              )}
              {hitlCountdown && (
                <p className="text-xs mono text-warning">Timeout in {hitlCountdown}</p>
              )}
              {hitlError && (
                <p className="text-xs text-destructive break-words max-w-[14rem] text-right">{hitlError}</p>
              )}
              <div className="flex items-center gap-2">
                {!humanControlling ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleTakeControl}
                    disabled={hitlBusy || takeControlPending}
                  >
                    <Hand className="h-3.5 w-3.5" />
                    {takeControlPending ? 'Taking control…' : 'Take control'}
                  </Button>
                ) : (
                  <Button size="sm" onClick={handleReturnControl} disabled={hitlBusy}>
                    Return control
                  </Button>
                )}
              </div>
            </div>
          )}
          {showReport && (
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/runs/${runId}/report`} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-3.5 w-3.5" />
                Report
              </a>
            </Button>
          )}
          {primaryAction && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => openNewRun(primaryAction.draft)}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Re-run
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
            <CompletedStepsPanel steps={run?.steps} isRunning={isRunning} isReplay={isReplay} />
            <RunStats
              stepCount={run?.steps.length}
              status={run?.status}
              elapsedS={run ? elapsedSeconds(run.started_at, run.finished_at) : undefined}
              tokens={run?.tokens}
              promptTokens={run?.prompt_tokens}
              completionTokens={run?.completion_tokens}
              cacheTokens={run?.cache_tokens}
              costUsd={run?.cost_usd}
              costBreakdown={run?.cost_breakdown}
              steps={run?.steps}
              typicalTiming={run ? aggregateTurnTiming(run.steps) : null}
              currentTiming={isRunning ? run?.turn_timing : undefined}
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

            {humanControlling && (
              <div className="border border-warning/40 rounded-lg px-4 py-2 bg-warning/10">
                <p className="text-xs text-warning">
                  You have browser control. Perform actions in the headed Chrome window, then return control to the agent.
                </p>
              </div>
            )}

            {run?.steps.map((step, i) => (
              <StepCard
                key={`${step.index}-${step.source ?? 'agent'}`}
                step={step}
                isActive={i === run.steps.length - 1 && isRunning}
                isReplay={isReplay}
              />
            ))}

            {run?.summary && !isRunning && (
              <div
                className={`rounded-lg px-4 py-3 border text-sm ${
                  run.status === 'pass'
                    ? 'bg-success/10 border-success/30 text-success'
                    : run.status === 'error'
                      ? 'bg-warning/10 border-warning/30 text-warning'
                      : 'bg-destructive/10 border-destructive/30 text-destructive'
                }`}
              >
                <strong>Summary:</strong> {run.summary}
                {run.criteria_verdict?.evidence && (
                  <p className="mt-1 text-xs opacity-90">{run.criteria_verdict.evidence}</p>
                )}
              </div>
            )}

            {run?.screen_excerpts && run.screen_excerpts.length > 0 && !isRunning && (
              <div className="rounded-lg px-4 py-3 border border-border text-sm">
                <strong>Earlier screens</strong>
                <ul className="mt-2 space-y-2 text-xs text-muted-foreground">
                  {run.screen_excerpts.map((excerpt, index) => (
                    <li key={`${excerpt.step}-${excerpt.url}-${index}`}>
                      <p>
                        step {excerpt.step}
                        {excerpt.title ? ` · ${excerpt.title}` : ''}
                      </p>
                      <pre className="mt-1 whitespace-pre-wrap font-sans opacity-90">
                        {excerpt.text}
                      </pre>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
