import { describe, expect, it } from 'vitest'
import { buildStartRunPayload, isTerminalRunStatus } from './project-run'
import type { Project, ProjectTask } from '@/types'

const project: Project = {
  id: 'proj-1',
  name: 'Demo',
  url: 'https://example.com',
  description: '',
  context_prompt: '',
  tasks: [],
}

function task(partial: Partial<ProjectTask> & Pick<ProjectTask, 'id' | 'task'>): ProjectTask {
  return {
    success_criteria: 'ok',
    headless: false,
    max_steps: 50,
    ...partial,
  }
}

describe('buildStartRunPayload', () => {
  it('starts training when not trained', () => {
    const payload = buildStartRunPayload(
      project,
      task({ id: 't1', task: 'Open home', name: 'Home' }),
    )
    expect(payload.use_replay_script).toBe(false)
    expect(payload.source_run_id).toBeUndefined()
    expect(payload.website_id).toBe('proj-1')
    expect(payload.website_task_id).toBe('t1')
    expect(payload.name).toBe('Home')
    expect(payload.run_mode).toBe('training')
  })

  it('starts automatic replay when trained', () => {
    const payload = buildStartRunPayload(
      project,
      task({
        id: 't2',
        task: 'Checkout',
        has_trained_replay: true,
        last_trained_run_id: 'trained-1',
      }),
    )
    expect(payload.use_replay_script).toBe(true)
    expect(payload.source_run_id).toBe('trained-1')
    expect(payload.run_mode).toBe('automatic')
  })

  it('forces training when forceTraining is set', () => {
    const payload = buildStartRunPayload(
      project,
      task({
        id: 't3',
        task: 'Checkout',
        has_trained_replay: true,
        last_trained_run_id: 'trained-1',
      }),
      { forceTraining: true },
    )
    expect(payload.use_replay_script).toBe(false)
    expect(payload.source_run_id).toBeUndefined()
    expect(payload.run_mode).toBe('training')
  })

  it('starts a headed manual demonstration when forceManual is set', () => {
    const payload = buildStartRunPayload(
      project,
      task({
        id: 't4',
        task: 'Human demonstration',
        has_trained_replay: true,
        last_trained_run_id: 'trained-1',
        headless: true,
      }),
      { forceManual: true },
    )
    expect(payload.run_mode).toBe('manual')
    expect(payload.task).toBe('')
    expect(payload.use_replay_script).toBe(false)
    expect(payload.headless).toBe(false)
    expect(payload.source_run_id).toBeUndefined()
  })
})

describe('isTerminalRunStatus', () => {
  it('recognizes terminal statuses', () => {
    expect(isTerminalRunStatus('pass')).toBe(true)
    expect(isTerminalRunStatus('fail')).toBe(true)
    expect(isTerminalRunStatus('error')).toBe(true)
    expect(isTerminalRunStatus('cancelled')).toBe(true)
    expect(isTerminalRunStatus('running')).toBe(false)
    expect(isTerminalRunStatus(null)).toBe(false)
  })
})
