import { describe, expect, it } from 'vitest'
import {
  countNeverRunTests,
  formatResultsSummary,
  latestRunForProjectTask,
  latestRunsByProjectTaskId,
  projectHasActiveRun,
  projectTaskHasActiveRun,
  projectTestResultsSummary,
  recentProjectRuns,
  resolveTestRowStatus,
  runsForProjectTask,
} from './project-task-status'
import type { RunSummary } from '@/types'

function run(partial: Partial<RunSummary> & Pick<RunSummary, 'run_id' | 'started_at'>): RunSummary {
  return {
    task: 'task',
    success_criteria: '',
    status: 'pass',
    step_count: 0,
    finished_at: partial.started_at + 10,
    summary: '',
    tokens: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    cache_tokens: 0,
    cost_usd: null,
    ...partial,
  }
}

describe('project-task-status', () => {
  it('picks latest run per task', () => {
    const runs = [
      run({
        run_id: 'a',
        started_at: 100,
        website_id: 'p1',
        website_task_id: 't1',
      }),
      run({
        run_id: 'b',
        started_at: 200,
        website_id: 'p1',
        website_task_id: 't1',
        status: 'fail',
      }),
    ]
    expect(latestRunForProjectTask(runs, 'p1', 't1')?.run_id).toBe('b')
    expect(latestRunsByProjectTaskId(runs, 'p1').get('t1')?.run_id).toBe('b')
  })

  it('counts never-run tests', () => {
    const runs = [
      run({
        run_id: 'a',
        started_at: 100,
        website_id: 'p1',
        website_task_id: 't1',
      }),
    ]
    const map = latestRunsByProjectTaskId(runs, 'p1')
    expect(countNeverRunTests([{ id: 't1' }, { id: 't2' }], map)).toBe(1)
  })

  it('prefers suite overlay when active', () => {
    const status = resolveTestRowStatus({
      latestRun: run({
        run_id: 'old',
        started_at: 50,
        website_id: 'p1',
        website_task_id: 't1',
        status: 'pass',
      }),
      suiteResult: { taskId: 't1', status: 'running', runId: 'live' },
      suiteActive: true,
    })
    expect(status.kind).toBe('suite')
    expect(status.label).toBe('Running')
    expect(status.runId).toBe('live')
  })

  it('falls back to historical run when suite idle', () => {
    const latest = run({
      run_id: 'hist',
      started_at: 50,
      website_id: 'p1',
      website_task_id: 't1',
      status: 'fail',
    })
    const status = resolveTestRowStatus({
      latestRun: latest,
      suiteActive: false,
    })
    expect(status.kind).toBe('run')
    expect(status.label).toBe('Fail')
    expect(status.runId).toBe('hist')
  })

  it('returns never-run when no history', () => {
    const status = resolveTestRowStatus({ suiteActive: false })
    expect(status).toEqual({ kind: 'never', label: 'Never run' })
  })

  it('lists recent project runs newest first', () => {
    const runs = [
      run({ run_id: '1', started_at: 10, website_id: 'p1' }),
      run({ run_id: '2', started_at: 30, website_id: 'p1' }),
      run({ run_id: '3', started_at: 20, website_id: 'p2' }),
    ]
    expect(recentProjectRuns(runs, 'p1', 2).map((r) => r.run_id)).toEqual(['2', '1'])
  })

  it('summarizes per-test latest outcomes', () => {
    const runs = [
      run({ run_id: 'a', started_at: 10, website_id: 'p1', website_task_id: 't1', status: 'pass' }),
      run({ run_id: 'b', started_at: 20, website_id: 'p1', website_task_id: 't2', status: 'fail' }),
      run({
        run_id: 'c',
        started_at: 30,
        website_id: 'p1',
        website_task_id: 't3',
        status: 'running',
        finished_at: null,
      }),
    ]
    const map = latestRunsByProjectTaskId(runs, 'p1')
    const summary = projectTestResultsSummary(
      [{ id: 't1' }, { id: 't2' }, { id: 't3' }, { id: 't4' }],
      map,
    )
    expect(summary).toEqual({
      passed: 1,
      failed: 1,
      running: 1,
      neverRun: 1,
      cancelled: 0,
    })
    expect(formatResultsSummary(summary)).toBe('1 passed · 1 failed · 1 running · 1 never run')
  })

  it('returns recent attempts for a task', () => {
    const runs = [
      run({ run_id: '1', started_at: 10, website_id: 'p1', website_task_id: 't1' }),
      run({ run_id: '2', started_at: 30, website_id: 'p1', website_task_id: 't1' }),
      run({ run_id: '3', started_at: 20, website_id: 'p1', website_task_id: 't1' }),
      run({ run_id: '4', started_at: 40, website_id: 'p1', website_task_id: 't2' }),
    ]
    expect(runsForProjectTask(runs, 'p1', 't1', 3).map((r) => r.run_id)).toEqual(['2', '3', '1'])
  })

  it('detects live runs for a task or project', () => {
    const runs = [
      run({
        run_id: 'live',
        started_at: 10,
        website_id: 'p1',
        website_task_id: 't1',
        status: 'running',
        finished_at: null,
      }),
      run({
        run_id: 'done',
        started_at: 20,
        website_id: 'p1',
        website_task_id: 't2',
        status: 'pass',
      }),
    ]
    expect(projectTaskHasActiveRun(runs, 'p1', 't1')).toBe(true)
    expect(projectTaskHasActiveRun(runs, 'p1', 't2')).toBe(false)
    expect(
      projectTaskHasActiveRun(
        [
          run({
            run_id: 'task-id-only-live',
            started_at: 50,
            website_task_id: 't2',
            status: 'awaiting_human',
            finished_at: null,
          }),
        ],
        'p1',
        't2',
      ),
    ).toBe(true)
    expect(projectHasActiveRun(runs, 'p1')).toBe(true)
    expect(projectHasActiveRun(runs, 'p2')).toBe(false)
    expect(
      projectHasActiveRun(
        [
          run({
            run_id: 'orphan-live',
            started_at: 40,
            website_task_id: 't1',
            status: 'running',
            finished_at: null,
          }),
        ],
        'p1',
        ['t1'],
      ),
    ).toBe(true)
  })
})
