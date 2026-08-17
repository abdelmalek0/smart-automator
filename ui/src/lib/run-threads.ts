import { isActiveRunStatus, isManualRun, runModeOf } from '@/lib/run-status'
import type { RunSummary } from '@/types'

export { isActiveRunStatus }

export interface TrainingNode {
  training: RunSummary
  automaticRuns: RunSummary[]
}

export interface TestRunTree {
  trainings: TrainingNode[]
  manuals: TrainingNode[]
  orphanAutomaticRuns: RunSummary[]
}

export interface RunTestGroup {
  id: string
  taskKey: string
  title: string
  /** Flat list of all runs in the test (for activity / expand checks). */
  runs: RunSummary[]
  trainings: TrainingNode[]
  manuals: TrainingNode[]
  orphanAutomaticRuns: RunSummary[]
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

function sortRunsNewestFirst(runs: RunSummary[]): RunSummary[] {
  return [...runs].sort((a, b) => b.started_at - a.started_at)
}

function isTrainingRun(run: RunSummary): boolean {
  return runModeOf(run) === 'training'
}

function isAuthoredRun(run: RunSummary): boolean {
  return !run.use_replay_script
}

function isAutomaticRun(run: RunSummary): boolean {
  return Boolean(run.use_replay_script)
}

/** Group authored runs as siblings; nest automatics under their source; else orphans. */
export function buildTestRunTree(runs: RunSummary[]): TestRunTree {
  const authored = sortRunsNewestFirst(runs.filter(isAuthoredRun))
  const authoredIds = new Set(authored.map((run) => run.run_id))
  const automaticBySource = new Map<string, RunSummary[]>()
  const orphanAutomaticRuns: RunSummary[] = []

  for (const run of sortRunsNewestFirst(runs.filter(isAutomaticRun))) {
    const sourceId = run.source_run_id
    if (sourceId && authoredIds.has(sourceId)) {
      const existing = automaticBySource.get(sourceId) ?? []
      existing.push(run)
      automaticBySource.set(sourceId, existing)
    } else {
      orphanAutomaticRuns.push(run)
    }
  }

  const nodes: TrainingNode[] = authored.map((source) => ({
    training: source,
    automaticRuns: automaticBySource.get(source.run_id) ?? [],
  }))

  return {
    trainings: nodes.filter((node) => isTrainingRun(node.training)),
    manuals: nodes.filter((node) => isManualRun(node.training)),
    orphanAutomaticRuns,
  }
}

export type RunModeFilter = 'all' | 'training' | 'manual' | 'automatic'

export const RUN_MODE_FILTERS: { value: RunModeFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'training', label: 'Training' },
  { value: 'manual', label: 'Manual' },
  { value: 'automatic', label: 'Automatic' },
]

/** Flat training runs for a test (newest first — already ordered in trainings). */
export function testTrainingRuns(test: RunTestGroup): RunSummary[] {
  return test.trainings.map((node) => node.training)
}

export function testManualRuns(test: RunTestGroup): RunSummary[] {
  return (test.manuals ?? []).map((node) => node.training)
}

/** Flat automatic runs for a test (attached + orphans), newest first. */
export function testAutomaticRuns(test: RunTestGroup): RunSummary[] {
  const attached = [
    ...test.trainings.flatMap((node) => node.automaticRuns),
    ...(test.manuals ?? []).flatMap((node) => node.automaticRuns),
  ]
  return sortRunsNewestFirst([...attached, ...test.orphanAutomaticRuns])
}

/** Ensure the active run is included when it falls outside the current window of a flat list. */
export function minimumVisibleSectionRuns(
  runs: RunSummary[],
  visibleCount: number,
  activeRunId: string | null,
): number {
  const total = runs.length
  if (!activeRunId) return Math.min(visibleCount, total)
  const index = runs.findIndex((run) => run.run_id === activeRunId)
  if (index < 0) return Math.min(visibleCount, total)
  return Math.min(Math.max(visibleCount, index + 1), total)
}

export function nextVisibleTestRunCount(current: number, total: number): number {
  return Math.min(current + TEST_RUNS_PAGE_SIZE, total)
}

/** Whether an automatic run's source training is still present in this test's training list. */
export function automaticSourceExistsInTest(run: RunSummary, test: RunTestGroup): boolean {
  if (!run.source_run_id) return false
  const authored = [...test.trainings, ...(test.manuals ?? [])]
  return authored.some((node) => node.training.run_id === run.source_run_id)
}

function taskGroupId(scopeId: string, taskKey: string): string {
  return `${scopeId}:task:${encodeURIComponent(taskKey)}`
}

function truncateTitle(taskKey: string): string {
  return taskKey.length > 36 ? `${taskKey.slice(0, 36)}…` : taskKey
}

function buildTestGroups(scopeId: string, runs: RunSummary[]): RunTestGroup[] {
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
      const tree = buildTestRunTree(testRuns)
      const sorted = sortRunsNewestFirst(testRuns)
      return {
        id: taskGroupId(scopeId, taskKey),
        taskKey,
        title: truncateTitle(taskKey),
        runs: sorted,
        trainings: tree.trainings,
        manuals: tree.manuals,
        orphanAutomaticRuns: tree.orphanAutomaticRuns,
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
      testGroups: buildTestGroups(`project:${projectId}`, projectRuns),
    }
  })
}

function buildUncategorizedThread(runs: RunSummary[]): RunThread | null {
  if (runs.length === 0) return null

  const sortedRuns = sortRunsNewestFirst(runs)
  return {
    id: UNCATEGORIZED_THREAD_ID,
    uncategorized: true,
    root: sortedRuns[0],
    runs: sortedRuns,
    testGroups: buildTestGroups(UNCATEGORIZED_THREAD_ID, runs),
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

export function runModeLabel(run: RunSummary): 'Training' | 'Manual' | 'Automatic' {
  const mode = runModeOf(run)
  if (mode === 'automatic') return 'Automatic'
  if (mode === 'manual') return 'Manual'
  return 'Training'
}

/** Oldest-first attempt number within one mode section (training and automatic count separately). */
export function sectionAttemptLabel(run: RunSummary, sectionRuns: RunSummary[]): string {
  const ordered = [...sectionRuns].sort((a, b) => a.started_at - b.started_at)
  const index = ordered.findIndex((item) => item.run_id === run.run_id) + 1
  return index > 0 ? `Attempt ${index}` : 'Attempt'
}

export function formatRunStartedLabel(startedAt: number): string {
  const date = new Date(startedAt * 1000)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
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

/** Whether any automatic run in the list still depends on this training for replay. */
export function hasAutomaticDependents(runId: string, runs: RunSummary[]): boolean {
  return runs.some(
    (run) => run.use_replay_script && run.source_run_id === runId && run.run_id !== runId,
  )
}
