import type { SuiteTaskResult, SuiteTaskStatus } from '@/hooks/useProjectSuiteRunner'
import { suiteStatusLabel } from '@/hooks/useProjectSuiteRunner'
import { isActiveRunStatus, statusLabel } from '@/lib/run-status'
import type { RunStatus, RunSummary } from '@/types'

export type TestRowStatusKind = 'never' | 'run' | 'suite'

export type TestRowStatus = {
  kind: TestRowStatusKind
  label: string
  runId?: string
  runStatus?: RunStatus
  suiteStatus?: SuiteTaskStatus
  startedAt?: number
  finishedAt?: number | null
}

const SUITE_TO_RUN_STATUS: Partial<Record<SuiteTaskStatus, RunStatus>> = {
  running: 'running',
  pass: 'pass',
  fail: 'fail',
  error: 'error',
  cancelled: 'cancelled',
}

export function latestRunForProjectTask(
  runs: RunSummary[],
  projectId: string,
  taskId: string,
): RunSummary | undefined {
  return runs
    .filter((r) => r.website_id === projectId && r.website_task_id === taskId)
    .sort((a, b) => b.started_at - a.started_at)[0]
}

export function projectTaskHasActiveRun(
  runs: RunSummary[],
  _projectId: string,
  taskId: string,
): boolean {
  return runs.some(
    (run) => run.website_task_id === taskId && isActiveRunStatus(run.status),
  )
}

export function projectHasActiveRun(
  runs: RunSummary[],
  projectId: string,
  taskIds?: Iterable<string>,
): boolean {
  const ids = taskIds ? new Set(taskIds) : null
  return runs.some((run) => {
    if (!isActiveRunStatus(run.status)) return false
    if (run.website_id === projectId) return true
    return Boolean(ids && run.website_task_id && ids.has(run.website_task_id))
  })
}

export function latestRunsByProjectTaskId(
  runs: RunSummary[],
  projectId: string,
): Map<string, RunSummary> {
  const map = new Map<string, RunSummary>()
  for (const run of runs) {
    if (run.website_id !== projectId || !run.website_task_id) continue
    const existing = map.get(run.website_task_id)
    if (!existing || run.started_at > existing.started_at) {
      map.set(run.website_task_id, run)
    }
  }
  return map
}

export function recentProjectRuns(
  runs: RunSummary[],
  projectId: string,
  limit = 10,
): RunSummary[] {
  return runs
    .filter((r) => r.website_id === projectId)
    .sort((a, b) => b.started_at - a.started_at)
    .slice(0, limit)
}

export function countNeverRunTests(
  tasks: { id: string }[],
  latestByTask: Map<string, RunSummary>,
): number {
  return tasks.filter((t) => !latestByTask.has(t.id)).length
}

export type ProjectTestResultsSummary = {
  passed: number
  failed: number
  neverRun: number
  running: number
  cancelled: number
}

export function projectTestResultsSummary(
  tasks: { id: string }[],
  latestByTask: Map<string, RunSummary>,
): ProjectTestResultsSummary {
  const summary: ProjectTestResultsSummary = {
    passed: 0,
    failed: 0,
    neverRun: 0,
    running: 0,
    cancelled: 0,
  }

  for (const task of tasks) {
    const latest = latestByTask.get(task.id)
    if (!latest) {
      summary.neverRun++
      continue
    }
    if (isActiveRunStatus(latest.status)) {
      summary.running++
    } else if (latest.status === 'pass') {
      summary.passed++
    } else if (latest.status === 'fail' || latest.status === 'error') {
      summary.failed++
    } else if (latest.status === 'cancelled') {
      summary.cancelled++
    }
  }

  return summary
}

export function runsForProjectTask(
  runs: RunSummary[],
  projectId: string,
  taskId: string,
  limit = 3,
): RunSummary[] {
  return runs
    .filter((r) => r.website_id === projectId && r.website_task_id === taskId)
    .sort((a, b) => b.started_at - a.started_at)
    .slice(0, limit)
}

export function formatResultsSummary(summary: ProjectTestResultsSummary): string {
  const parts: string[] = []
  if (summary.passed > 0) {
    parts.push(`${summary.passed} passed`)
  }
  if (summary.failed > 0) {
    parts.push(`${summary.failed} failed`)
  }
  if (summary.running > 0) {
    parts.push(`${summary.running} running`)
  }
  if (summary.cancelled > 0) {
    parts.push(`${summary.cancelled} cancelled`)
  }
  if (summary.neverRun > 0) {
    parts.push(`${summary.neverRun} never run`)
  }
  return parts.length > 0 ? parts.join(' · ') : 'No results yet'
}

export function resolveTestRowStatus({
  latestRun,
  suiteResult,
  suiteActive,
}: {
  latestRun?: RunSummary
  suiteResult?: SuiteTaskResult
  suiteActive: boolean
}): TestRowStatus {
  if (suiteActive && suiteResult && suiteResult.status !== 'skipped') {
    if (suiteResult.status === 'queued') {
      return {
        kind: 'suite',
        label: suiteStatusLabel('queued'),
        suiteStatus: 'queued',
        runId: suiteResult.runId,
      }
    }

    const mapped = SUITE_TO_RUN_STATUS[suiteResult.status]
    if (mapped) {
      return {
        kind: 'suite',
        label: suiteStatusLabel(suiteResult.status),
        suiteStatus: suiteResult.status,
        runStatus: mapped,
        runId: suiteResult.runId,
      }
    }
  }

  if (!latestRun) {
    return { kind: 'never', label: 'Never run' }
  }

  return {
    kind: 'run',
    label: statusLabel(latestRun.status),
    runStatus: latestRun.status,
    runId: latestRun.run_id,
    startedAt: latestRun.started_at,
    finishedAt: latestRun.finished_at,
  }
}
