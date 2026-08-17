import { describe, expect, it } from 'vitest'
import {
  allThreadExpandIds,
  automaticSourceExistsInTest,
  buildRunThreads,
  buildTestRunTree,
  collectAutoExpandIds,
  hasAutomaticDependents,
  INITIAL_TEST_RUNS_VISIBLE,
  minimumVisibleSectionRuns,
  nextVisibleTestRunCount,
  TEST_RUNS_PAGE_SIZE,
  testAutomaticRuns,
  testManualRuns,
  testTrainingRuns,
  sectionAttemptLabel,
  UNCATEGORIZED_THREAD_ID,
  type RunTestGroup,
} from './run-threads'
import type { RunSummary } from '@/types'

function mockRun(
  id: string,
  startedAt: number,
  opts: Partial<RunSummary> = {},
): RunSummary {
  return {
    run_id: id,
    task: 'task',
    success_criteria: 'ok',
    use_replay_script: false,
    status: 'pass',
    step_count: 1,
    started_at: startedAt,
    finished_at: startedAt + 1000,
    summary: '',
    tokens: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    cache_tokens: 0,
    cost_usd: null,
    ...opts,
  }
}

describe('visible section run helpers', () => {
  const runs = Array.from({ length: 15 }, (_, i) => mockRun(`run-${i}`, 1000 - i))

  it('keeps default visible count when active run is in window', () => {
    expect(minimumVisibleSectionRuns(runs, INITIAL_TEST_RUNS_VISIBLE, 'run-1')).toBe(3)
  })

  it('expands visible count to include active run beyond window', () => {
    expect(minimumVisibleSectionRuns(runs, INITIAL_TEST_RUNS_VISIBLE, 'run-12')).toBe(13)
  })

  it('reveals runs in batches of TEST_RUNS_PAGE_SIZE', () => {
    expect(nextVisibleTestRunCount(3, 15)).toBe(13)
    expect(nextVisibleTestRunCount(13, 15)).toBe(15)
  })
})

describe('flat section helpers', () => {
  it('flattens trainings and automatics including orphans', () => {
    const t1 = mockRun('t1', 100)
    const a1 = mockRun('a1', 150, { use_replay_script: true, source_run_id: 't1' })
    const orphan = mockRun('orphan', 200, {
      use_replay_script: true,
      source_run_id: 'gone',
    })
    const tree = buildTestRunTree([t1, a1, orphan])
    const test: RunTestGroup = {
      id: 'test-1',
      taskKey: 'Login',
      title: 'Login',
      runs: [t1, a1, orphan],
      trainings: tree.trainings,
      manuals: tree.manuals,
      orphanAutomaticRuns: tree.orphanAutomaticRuns,
    }

    expect(testTrainingRuns(test).map((r) => r.run_id)).toEqual(['t1'])
    expect(testAutomaticRuns(test).map((r) => r.run_id)).toEqual(['orphan', 'a1'])
    expect(automaticSourceExistsInTest(a1, test)).toBe(true)
    expect(automaticSourceExistsInTest(orphan, test)).toBe(false)
  })
})

describe('sectionAttemptLabel', () => {
  it('numbers oldest-first within a section independently of display order', () => {
    const oldest = mockRun('oldest', 100)
    const middle = mockRun('middle', 200)
    const newest = mockRun('newest', 300)
    // Section lists are typically newest-first
    const section = [newest, middle, oldest]

    expect(sectionAttemptLabel(oldest, section)).toBe('Attempt 1')
    expect(sectionAttemptLabel(middle, section)).toBe('Attempt 2')
    expect(sectionAttemptLabel(newest, section)).toBe('Attempt 3')
  })
})

describe('buildTestRunTree', () => {
  it('nests automatic runs under their source training and keeps trainings as siblings', () => {
    const t1 = mockRun('t1', 100)
    const t2 = mockRun('t2', 300)
    const tFail = mockRun('t-fail', 200, { status: 'fail' })
    const a1 = mockRun('a1', 150, { use_replay_script: true, source_run_id: 't1' })
    const a2 = mockRun('a2', 250, { use_replay_script: true, source_run_id: 't1' })
    const a3 = mockRun('a3', 350, { use_replay_script: true, source_run_id: 't2' })
    // Training→training lineage must not nest
    const tRetry = mockRun('t-retry', 280, { source_run_id: 't1' })

    const tree = buildTestRunTree([t1, t2, tFail, a1, a2, a3, tRetry])
    expect(tree.trainings.map((n) => n.training.run_id)).toEqual(['t2', 't-retry', 't-fail', 't1'])
    expect(tree.trainings.find((n) => n.training.run_id === 't1')?.automaticRuns.map((r) => r.run_id)).toEqual([
      'a2',
      'a1',
    ])
    expect(tree.trainings.find((n) => n.training.run_id === 't2')?.automaticRuns.map((r) => r.run_id)).toEqual([
      'a3',
    ])
    expect(tree.trainings.find((n) => n.training.run_id === 't-retry')?.automaticRuns).toEqual([])
    expect(tree.orphanAutomaticRuns).toEqual([])
  })

  it('nests automatic runs under a manual source', () => {
    const m1 = mockRun('m1', 100, { run_mode: 'manual' })
    const a1 = mockRun('a1', 150, { use_replay_script: true, source_run_id: 'm1' })
    const tree = buildTestRunTree([m1, a1])
    expect(tree.trainings).toEqual([])
    expect(tree.manuals.map((n) => n.training.run_id)).toEqual(['m1'])
    expect(tree.manuals[0].automaticRuns.map((r) => r.run_id)).toEqual(['a1'])
    const test: RunTestGroup = {
      id: 'test-1',
      taskKey: 'Login',
      title: 'Login',
      runs: [m1, a1],
      trainings: tree.trainings,
      manuals: tree.manuals,
      orphanAutomaticRuns: tree.orphanAutomaticRuns,
    }
    expect(testManualRuns(test).map((r) => r.run_id)).toEqual(['m1'])
    expect(testAutomaticRuns(test).map((r) => r.run_id)).toEqual(['a1'])
    expect(automaticSourceExistsInTest(a1, test)).toBe(true)
  })

  it('places automatic runs with missing source under orphans', () => {
    const orphan = mockRun('orphan', 100, {
      use_replay_script: true,
      source_run_id: 'deleted-training',
    })
    const tree = buildTestRunTree([orphan])
    expect(tree.trainings).toEqual([])
    expect(tree.orphanAutomaticRuns.map((r) => r.run_id)).toEqual(['orphan'])
  })
})

describe('collectAutoExpandIds', () => {
  it('returns only the project and test group for the active run', () => {
    const threads = buildRunThreads([
      { ...mockRun('p1-run', 100), website_id: 'site-1', task: 'Homepage' },
      { ...mockRun('p2-run', 90), website_id: 'site-1', task: 'Login' },
      { ...mockRun('other', 80), website_id: 'site-2', task: 'Checkout' },
    ])

    const ids = collectAutoExpandIds(threads, 'p2-run')
    expect(ids.has('project:site-1')).toBe(true)
    expect(ids.has('project:site-2')).toBe(false)
    expect([...ids].some((id) => id.includes('Login'))).toBe(true)
    expect([...ids].some((id) => id.includes('Homepage'))).toBe(false)
  })

  it('includes threads with live runs when no activeRunId', () => {
    const threads = buildRunThreads([
      { ...mockRun('live', 100), website_id: 'site-1', task: 'Homepage', status: 'running' },
      { ...mockRun('done', 90), website_id: 'site-2', task: 'Checkout', status: 'pass' },
    ])

    const ids = collectAutoExpandIds(threads, null)
    expect(ids.has('project:site-1')).toBe(true)
    expect(ids.has('project:site-2')).toBe(false)
  })
})

describe('allThreadExpandIds', () => {
  it('includes every project and test group id', () => {
    const threads = buildRunThreads([
      { ...mockRun('p1', 100), website_id: 'site-1', task: 'Homepage' },
      { ...mockRun('a1', 100), task: 'Login flow' },
      {
        ...mockRun('a2', 200),
        task: 'Login flow',
        use_replay_script: true,
        source_run_id: 'a1',
      },
    ])

    const ids = allThreadExpandIds(threads)
    expect(ids.has('project:site-1')).toBe(true)
    expect(ids.has(UNCATEGORIZED_THREAD_ID)).toBe(true)
    expect([...ids].some((id) => id.includes('Homepage'))).toBe(true)
    expect([...ids].some((id) => id.includes('Login'))).toBe(true)
  })
})

describe('buildRunThreads', () => {
  it('groups standalone runs under Uncategorized by task, nesting autos under trainings', () => {
    const standalone = [
      { ...mockRun('a1', 100), task: 'Login flow' },
      {
        ...mockRun('a2', 200),
        task: 'Login flow',
        use_replay_script: true,
        source_run_id: 'a1',
      },
      { ...mockRun('b1', 150), task: 'Checkout' },
    ]

    const threads = buildRunThreads(standalone)
    expect(threads).toHaveLength(1)
    expect(threads[0].id).toBe(UNCATEGORIZED_THREAD_ID)
    expect(threads[0].uncategorized).toBe(true)
    expect(threads[0].testGroups).toHaveLength(2)

    const login = threads[0].testGroups?.find((g) => g.taskKey === 'Login flow')
    expect(login?.trainings).toHaveLength(1)
    expect(login?.trainings[0].automaticRuns).toHaveLength(1)
    expect(login?.trainings[0].automaticRuns[0].run_id).toBe('a2')
  })

  it('does not nest training under training via source_run_id', () => {
    const threads = buildRunThreads([
      { ...mockRun('t1', 100), task: 'Login flow' },
      { ...mockRun('t2', 200), task: 'Login flow', source_run_id: 't1' },
    ])
    const group = threads[0].testGroups?.[0]
    expect(group?.trainings).toHaveLength(2)
    expect(group?.trainings.every((n) => n.automaticRuns.length === 0)).toBe(true)
  })

  it('keeps website runs as separate project threads', () => {
    const runs = [
      { ...mockRun('p1', 100), website_id: 'site-1', task: 'Homepage' },
      mockRun('s1', 50),
    ]

    const threads = buildRunThreads(runs)
    expect(threads).toHaveLength(2)
    expect(threads.some((thread) => thread.projectId === 'site-1')).toBe(true)
    expect(threads.some((thread) => thread.uncategorized)).toBe(true)
  })
})

describe('hasAutomaticDependents', () => {
  it('detects automatic children of a training run', () => {
    const runs = [
      mockRun('t1', 100),
      mockRun('a1', 200, { use_replay_script: true, source_run_id: 't1' }),
    ]
    expect(hasAutomaticDependents('t1', runs)).toBe(true)
    expect(hasAutomaticDependents('a1', runs)).toBe(false)
  })
})
