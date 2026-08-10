import { useQuery } from '@tanstack/react-query'
import { getConfig, getWorkerStatus, listRuns } from '@/api'

const ACTIVE_RUN_STATUSES = new Set(['pending', 'running', 'awaiting_human'])
const BUSY_BROWSER_STATES = new Set(['starting', 'ready', 'stopping'])

export type RunStartBlockReason = 'offline' | 'busy'

export type RunStartGate = {
  canStartRun: boolean
  blockReason: RunStartBlockReason | null
  blockHint: string | null
  connectOnline: boolean
  hasActiveRun: boolean
  browserBusy: boolean
}

function isActiveRunStatus(status: string): boolean {
  return ACTIVE_RUN_STATUSES.has(status)
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
  const leasedRun = leasedRunId ? runs.find((run) => run.run_id === leasedRunId) : null
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

  return {
    canStartRun: blockReason === null,
    blockReason,
    blockHint,
    connectOnline,
    hasActiveRun,
    browserBusy,
  }
}
