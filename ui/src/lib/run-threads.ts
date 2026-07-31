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
  testGroups?: RunTestGroup[]
}

const ACTIVE_STATUSES: RunStatus[] = ['pending', 'running', 'awaiting_human']

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

export function buildRunThreads(runs: RunSummary[]): RunThread[] {
  const projectRuns = runs.filter((run) => run.website_id)
  const standaloneRuns = runs.filter((run) => !run.website_id)

  const threads = [...buildProjectThreads(projectRuns), ...buildChainThreads(standaloneRuns)]

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

export function testHasActiveRun(test: RunTestGroup): boolean {
  return test.runs.some((run) => isActiveRunStatus(run.status))
}

export function testRunLabel(run: RunSummary, test: RunTestGroup): string {
  const mode = run.use_replay_script ? 'Automatic' : 'Training'
  const sameMode = sortRunsOldestFirst(
    test.runs.filter(
      (item) => Boolean(item.use_replay_script) === Boolean(run.use_replay_script),
    ),
  )
  if (sameMode.length <= 1) return mode
  const index = sameMode.findIndex((item) => item.run_id === run.run_id) + 1
  return `${mode} ${index}`
}

export function threadTitle(
  thread: RunThread,
  projectNames: Record<string, string> = {},
): string {
  if (thread.projectId) {
    return projectNames[thread.projectId] ?? 'Project'
  }
  return thread.root.name || thread.root.task
}

export function threadRunLabel(run: RunSummary, thread: RunThread): string {
  const mode = run.use_replay_script ? 'Automatic' : 'Training'

  if (thread.projectId) {
    const taskKey = run.name || run.task
    const taskShort = taskKey.length > 36 ? `${taskKey.slice(0, 36)}…` : taskKey
    const matches = sortRunsOldestFirst(
      thread.runs.filter(
        (item) =>
          (item.name || item.task) === taskKey &&
          Boolean(item.use_replay_script) === Boolean(run.use_replay_script),
      ),
    )
    if (matches.length <= 1) return `${taskShort} · ${mode}`
    const index = matches.findIndex((item) => item.run_id === run.run_id) + 1
    return `${taskShort} · ${mode} ${index}`
  }

  const sameMode = sortRunsOldestFirst(
    thread.runs.filter(
      (item) => Boolean(item.use_replay_script) === Boolean(run.use_replay_script),
    ),
  )
  if (sameMode.length <= 1) return mode
  const index = sameMode.findIndex((item) => item.run_id === run.run_id) + 1
  return `${mode} ${index}`
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

/** True when the thread needs a header row (project bucket or multi-run chain). */
export function threadIsGrouped(thread: RunThread): boolean {
  return Boolean(thread.projectId) || thread.runs.length > 1
}
