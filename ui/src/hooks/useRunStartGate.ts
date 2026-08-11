import { useQuery } from '@tanstack/react-query'
import { getConfig, getWorkerStatus, listRuns } from '@/api'
import { isActiveRunStatus } from '@/lib/run-status'
import type { RunSummary } from '@/types'

const BUSY_BROWSER_STATES = new Set(['starting', 'ready', 'stopping'])

export type RunStartBlockReason = 'offline' | 'busy'

export type AgentPhase = 'offline' | 'connected' | 'starting' | 'running' | 'awaiting_human'

export type RunStartGate = {
  canStartRun: boolean
  blockReason: RunStartBlockReason | null
  blockHint: string | null
  connectOnline: boolean
  hasActiveRun: boolean
  browserBusy: boolean
  activeRun: RunSummary | null
  agentPhase: AgentPhase
  localBrowserMode: boolean
}

function resolveActiveRun(
  runs: RunSummary[],
  leasedRun: RunSummary | null,
  leasedRunActive: boolean,
): RunSummary | null {
  if (leasedRunActive && leasedRun) return leasedRun
  return runs.find((run) => isActiveRunStatus(run.status)) ?? null
}

function resolveAgentPhase(
  localBrowserMode: boolean,
  connectOnline: boolean,
  activeRun: RunSummary | null,
): AgentPhase {
  if (!localBrowserMode && !connectOnline) return 'offline'
  if (!activeRun) return 'connected'
  switch (activeRun.status) {
    case 'pending':
      return 'starting'
    case 'running':
      return 'running'
    case 'awaiting_human':
      return 'awaiting_human'
    default:
      return 'connected'
  }
}

export function useRunStartGate(): RunStartGate {
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
  })
  const { data: workerStatus } = useQuery({
    queryKey: ['workerStatus'],
    queryFn: getWorkerStatus,
    refetchInterval: 5000,
  })
  const { data: runs = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: listRuns,
    refetchInterval: 3000,
  })

  const localBrowserMode = Boolean(config?.local_browser_mode)
  const connectOnline = Boolean(workerStatus?.online ?? config?.connect_online)
  const hasActiveRun = runs.some((run) => isActiveRunStatus(run.status))

  const leasedRunId = workerStatus?.active_run_id ?? null
  const leasedRun = leasedRunId ? runs.find((run) => run.run_id === leasedRunId) ?? null : null
  const leasedRunActive = Boolean(leasedRun && isActiveRunStatus(leasedRun.status))

  const browserStateBusy = Boolean(
    connectOnline &&
      workerStatus?.browser_state &&
      BUSY_BROWSER_STATES.has(workerStatus.browser_state),
  )
  const browserBusy = Boolean(
    browserStateBusy && (leasedRunActive || (leasedRunId == null && hasActiveRun)),
  )

  let blockReason: RunStartBlockReason | null = null
  let blockHint: string | null = null

  if (!localBrowserMode && !connectOnline) {
    blockReason = 'offline'
    blockHint = 'Connect app offline — log in to the Connect app to start runs.'
  } else if (hasActiveRun || browserBusy) {
    blockReason = 'busy'
    blockHint = 'Finish or cancel the current run before starting another.'
  }

  const activeRun = resolveActiveRun(runs, leasedRun, leasedRunActive)
  const agentPhase = resolveAgentPhase(localBrowserMode, connectOnline, activeRun)

  return {
    canStartRun: blockReason === null,
    blockReason,
    blockHint,
    connectOnline,
    hasActiveRun,
    browserBusy,
    activeRun,
    agentPhase,
    localBrowserMode,
  }
}
