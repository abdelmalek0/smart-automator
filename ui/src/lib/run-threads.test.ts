import { describe, expect, it } from 'vitest'
import {
  allThreadExpandIds,
  buildRunThreads,
  collectAutoExpandIds,
  INITIAL_TEST_RUNS_VISIBLE,
  minimumVisibleTestRuns,
  nextVisibleTestRunCount,
  TEST_RUNS_PAGE_SIZE,
  testRunLabel,
  threadRunLabel,
  UNCATEGORIZED_THREAD_ID,
  type RunTestGroup,
  type RunThread,
} from './run-threads'
import type { RunSummary } from '@/types'

function mockRun(id: string, startedAt: number, useReplayScript = false): RunSummary {
  return {
    run_id: id,
    task: 'task',
    success_criteria: 'ok',
    use_replay_script: useReplayScript,
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
  }
}

describe('visible test run helpers', () => {
  const runs = Array.from({ length: 15 }, (_, i) => mockRun(`run-${i}`, 1000 - i))

  it('keeps default visible count when active run is in window', () => {
    expect(minimumVisibleTestRuns(runs, INITIAL_TEST_RUNS_VISIBLE, 'run-1')).toBe(3)
  })

  it('expands visible count to include active run beyond window', () => {
    expect(minimumVisibleTestRuns(runs, INITIAL_TEST_RUNS_VISIBLE, 'run-12')).toBe(13)
  })

  it('reveals runs in batches of TEST_RUNS_PAGE_SIZE', () => {
    expect(nextVisibleTestRunCount(3, 15)).toBe(13)
    expect(nextVisibleTestRunCount(13, 15)).toBe(15)
  })
})

describe('testRunLabel', () => {
  it('returns oldest-first attempt ordinals', () => {
    const test: RunTestGroup = {
      id: 'test-1',
      taskKey: 'Login',
      title: 'Login',
      runs: [mockRun('newest', 300), mockRun('oldest', 100), mockRun('middle', 200)],
    }

    expect(testRunLabel(test.runs[0], test)).toBe('Attempt 3')
    expect(testRunLabel(test.runs[1], test)).toBe('Attempt 1')
    expect(testRunLabel(test.runs[2], test)).toBe('Attempt 2')
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
      { ...mockRun('a2', 200), task: 'Login flow', source_run_id: 'a1' },
    ])

    const ids = allThreadExpandIds(threads)
    expect(ids.has('project:site-1')).toBe(true)
    expect(ids.has(UNCATEGORIZED_THREAD_ID)).toBe(true)
    expect([...ids].some((id) => id.includes('Homepage'))).toBe(true)
    expect([...ids].some((id) => id.startsWith('run:'))).toBe(true)
  })
})

describe('buildRunThreads', () => {
  it('groups standalone runs under Uncategorized with test groups per chain', () => {
    const standalone = [
      { ...mockRun('a1', 100), task: 'Login flow' },
      { ...mockRun('a2', 200), task: 'Login flow', source_run_id: 'a1' },
      { ...mockRun('b1', 150), task: 'Checkout' },
    ]

    const threads = buildRunThreads(standalone)
    expect(threads).toHaveLength(1)
    expect(threads[0].id).toBe(UNCATEGORIZED_THREAD_ID)
    expect(threads[0].uncategorized).toBe(true)
    expect(threads[0].testGroups).toHaveLength(2)
    expect(threads[0].testGroups?.[0].runs).toHaveLength(2)
    expect(threads[0].testGroups?.[1].runs).toHaveLength(1)
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

describe('threadRunLabel', () => {
  it('returns oldest-first attempt ordinals', () => {
    const thread: RunThread = {
      id: 'run:root',
      root: mockRun('oldest', 100),
      runs: [mockRun('newest', 300), mockRun('oldest', 100)],
    }

    expect(threadRunLabel(thread.runs[0], thread)).toBe('Attempt 2')
    expect(threadRunLabel(thread.runs[1], thread)).toBe('Attempt 1')
  })
})
