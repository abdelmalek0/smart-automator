import type { RunStatus, RunSummary } from '@/types'

export interface RunTestGroup {
  id: string
  taskKey: string
  title: string
  runs: RunSummary[]
}

export interface RunThread {
  id: string
  root: RunSummary
  runs: RunSummary[]
  projectId?: string | null
  uncategorized?: boolean
  testGroups?: RunTestGroup[]
}

export const UNCATEGORIZED_THREAD_ID = 'uncategorized'
export const INITIAL_TEST_RUNS_VISIBLE = 3
export const TEST_RUNS_PAGE_SIZE = 10

const ACTIVE_STATUSES: RunStatus[] = ['pending', 'running', 'awaiting_human']

/** Ensure the active run is included when it falls outside the current window. */
export function minimumVisibleTestRuns(
  runs: RunSummary[],
  visibleCount: number,
  activeRunId: string | null,
): number {
  if (!activeRunId) return visibleCount
  const index = runs.findIndex((run) => run.run_id === activeRunId)
  if (index < 0) return visibleCount
  return Math.max(visibleCount, index + 1)
}

export function nextVisibleTestRunCount(current: number, total: number): number {
  return Math.min(current + TEST_RUNS_PAGE_SIZE, total)
}

function sortRunsNewestFirst(runs: RunSummary[]): RunSummary[] {
  return [...runs].sort((a, b) => b.started_at - a.started_at)
}

function sortRunsOldestFirst(runs: RunSummary[]): RunSummary[] {
  return [...runs].sort((a, b) => a.started_at - b.started_at)
}

function resolveRoot(run: RunSummary, byId: Map<string, RunSummary>): RunSummary {
  const seen = new Set<string>()
  let current = run

  while (current.source_run_id) {
    if (seen.has(current.source_run_id)) break
    seen.add(current.run_id)
    const parent = byId.get(current.source_run_id)
    if (!parent) break
    current = parent
  }

  return current
}

function buildChainThreads(runs: RunSummary[]): RunThread[] {
  const byId = new Map(runs.map((run) => [run.run_id, run]))
  const grouped = new Map<string, RunSummary[]>()

  for (const run of runs) {
    const root = resolveRoot(run, byId)
    const existing = grouped.get(root.run_id) ?? []
    if (!existing.some((item) => item.run_id === run.run_id)) {
      existing.push(run)
    }
    grouped.set(root.run_id, existing)
  }

  return Array.from(grouped.entries()).map(([rootId, threadRuns]) => {
    const sortedRuns = sortRunsNewestFirst(threadRuns)
    const root = byId.get(rootId) ?? sortedRuns[sortedRuns.length - 1]
    return {
      id: `run:${rootId}`,
      root,
      runs: sortedRuns,
    }
  })
}

function taskGroupId(projectId: string, taskKey: string): string {
  return `project:${projectId}:task:${encodeURIComponent(taskKey)}`
}

function buildTestGroups(projectId: string, runs: RunSummary[]): RunTestGroup[] {
  const grouped = new Map<string, RunSummary[]>()

  for (const run of runs) {
    const taskKey = run.name || run.task
    const existing = grouped.get(taskKey) ?? []
    if (!existing.some((item) => item.run_id === run.run_id)) {
      existing.push(run)
    }
    grouped.set(taskKey, existing)
  }

  return Array.from(grouped.entries())
    .map(([taskKey, testRuns]) => {
      const sorted = sortRunsNewestFirst(testRuns)
      const title = taskKey.length > 36 ? `${taskKey.slice(0, 36)}…` : taskKey
      return {
        id: taskGroupId(projectId, taskKey),
        taskKey,
        title,
        runs: sorted,
      }
    })
    .sort((a, b) => latestTestActivity(b) - latestTestActivity(a))
}

function buildProjectThreads(runs: RunSummary[]): RunThread[] {
  const grouped = new Map<string, RunSummary[]>()

  for (const run of runs) {
    if (!run.website_id) continue
    const existing = grouped.get(run.website_id) ?? []
    if (!existing.some((item) => item.run_id === run.run_id)) {
      existing.push(run)
    }
    grouped.set(run.website_id, existing)
  }

  return Array.from(grouped.entries()).map(([projectId, projectRuns]) => {
    const sortedRuns = sortRunsNewestFirst(projectRuns)
    const latest = sortedRuns[0]
    return {
      id: `project:${projectId}`,
      projectId,
      root: latest,
      runs: sortedRuns,
      testGroups: buildTestGroups(projectId, projectRuns),
    }
  })
}

function buildUncategorizedThread(runs: RunSummary[]): RunThread | null {
  if (runs.length === 0) return null

  const chains = buildChainThreads(runs)
  const sortedRuns = sortRunsNewestFirst(runs)

  const testGroups: RunTestGroup[] = chains
    .map((chain) => {
      const taskKey = chain.root.name || chain.root.task
      const title = taskKey.length > 36 ? `${taskKey.slice(0, 36)}…` : taskKey
      return {
        id: chain.id,
        taskKey,
        title,
        runs: chain.runs,
      }
    })
    .sort((a, b) => latestTestActivity(b) - latestTestActivity(a))

  return {
    id: UNCATEGORIZED_THREAD_ID,
    uncategorized: true,
    root: sortedRuns[0],
    runs: sortedRuns,
    testGroups,
  }
}

export function buildRunThreads(runs: RunSummary[]): RunThread[] {
  const projectRuns = runs.filter((run) => run.website_id)
  const standaloneRuns = runs.filter((run) => !run.website_id)

  const threads = [...buildProjectThreads(projectRuns)]
  const uncategorized = buildUncategorizedThread(standaloneRuns)
  if (uncategorized) {
    threads.push(uncategorized)
  }

  threads.sort((a, b) => latestThreadActivity(b) - latestThreadActivity(a))
  return threads
}

export function isActiveRunStatus(status: RunStatus): boolean {
  return ACTIVE_STATUSES.includes(status)
}

export function threadShouldExpand(thread: RunThread, activeRunId: string | null): boolean {
  if (activeRunId && thread.runs.some((run) => run.run_id === activeRunId)) {
    return true
  }
  if (thread.testGroups?.some((test) => testGroupShouldExpand(test, activeRunId))) {
    return true
  }
  return thread.runs.some((run) => isActiveRunStatus(run.status))
}

export function latestThreadActivity(thread: RunThread): number {
  return Math.max(...thread.runs.map((run) => run.started_at))
}

export function latestTestActivity(test: RunTestGroup): number {
  return Math.max(...test.runs.map((run) => run.started_at))
}

export function testLatestRun(test: RunTestGroup): RunSummary {
  return test.runs[0]
}

export function testStatusRun(test: RunTestGroup, activeRunId: string | null): RunSummary {
  if (activeRunId) {
    const active = test.runs.find((run) => run.run_id === activeRunId)
    if (active) return active
  }
  return testLatestRun(test)
}

export function testGroupShouldExpand(test: RunTestGroup, activeRunId: string | null): boolean {
  if (activeRunId && test.runs.some((run) => run.run_id === activeRunId)) {
    return true
  }
  return test.runs.some((run) => isActiveRunStatus(run.status))
}

/** Project and test-group ids that should be expanded for the active run / live runs. */
export function collectAutoExpandIds(
  threads: RunThread[],
  activeRunId: string | null,
): Set<string> {
  const ids = new Set<string>()
  for (const thread of threads) {
    if (threadShouldExpand(thread, activeRunId)) {
      ids.add(thread.id)
    }
    for (const test of thread.testGroups ?? []) {
      if (testGroupShouldExpand(test, activeRunId)) {
        ids.add(thread.id)
        ids.add(test.id)
      }
    }
  }
  return ids
}

export function testHasActiveRun(test: RunTestGroup): boolean {
  return test.runs.some((run) => isActiveRunStatus(run.status))
}

export function testRunLabel(run: RunSummary, test: RunTestGroup): string {
  const ordered = sortRunsOldestFirst(test.runs)
  const index = ordered.findIndex((item) => item.run_id === run.run_id) + 1
  return `Attempt ${index}`
}

export function threadTitle(
  thread: RunThread,
  projectNames: Record<string, string> = {},
): string {
  if (thread.uncategorized) {
    return 'Uncategorized'
  }
  if (thread.projectId) {
    return projectNames[thread.projectId] ?? 'Project'
  }
  return thread.root.name || thread.root.task
}

export function threadRunLabel(run: RunSummary, thread: RunThread): string {
  const ordered = sortRunsOldestFirst(thread.runs)
  const index = ordered.findIndex((item) => item.run_id === run.run_id) + 1
  return `Attempt ${index}`
}

export function threadHasActiveRun(thread: RunThread): boolean {
  return thread.runs.some((run) => isActiveRunStatus(run.status))
}

export function sortThreadsForSidebar(threads: RunThread[]): RunThread[] {
  return [...threads].sort((a, b) => {
    const aActive = threadHasActiveRun(a)
    const bActive = threadHasActiveRun(b)
    if (aActive !== bActive) return aActive ? -1 : 1
    return latestThreadActivity(b) - latestThreadActivity(a)
  })
}

export function threadLatestRun(thread: RunThread): RunSummary {
  return thread.runs[0]
}

export function threadStatusRun(thread: RunThread, activeRunId: string | null): RunSummary {
  if (activeRunId) {
    const active = thread.runs.find((run) => run.run_id === activeRunId)
    if (active) return active
  }
  return threadLatestRun(thread)
}

/** Expand every project/section and test group in the sidebar tree. */
export function allThreadExpandIds(threads: RunThread[]): Set<string> {
  const ids = new Set<string>()
  for (const thread of threads) {
    ids.add(thread.id)
    for (const test of thread.testGroups ?? []) {
      ids.add(test.id)
    }
  }
  return ids
}
