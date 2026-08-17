import { describe, expect, it } from 'vitest'
import {
  getPrimaryRunAction,
  runSummaryToDraft,
  toAutomaticDraft,
  toManualDraft,
  toTrainingDraft,
} from './run-draft'
import type { Project, RunSummary } from '@/types'

function mockRun(partial: Partial<RunSummary> & Pick<RunSummary, 'run_id'>): RunSummary {
  return {
    task: 'Do the thing',
    success_criteria: 'Done',
    use_replay_script: false,
    status: 'pass',
    step_count: 1,
    started_at: 100,
    finished_at: 200,
    summary: '',
    tokens: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    cache_tokens: 0,
    cost_usd: null,
    ...partial,
  }
}

describe('toTrainingDraft', () => {
  it('includes source_run_id when automatic replay is available for mode switching', () => {
    const draft = toTrainingDraft(
      mockRun({ run_id: 't1', has_replay_script: true, status: 'pass' }),
    )
    expect(draft.use_replay_script).toBe(false)
    expect(draft.source_run_id).toBe('t1')
    expect(draft.run_mode).toBe('training')
  })

  it('omits source_run_id when no replay is available', () => {
    const draft = toTrainingDraft(
      mockRun({ run_id: 't1', source_run_id: 'other', status: 'fail' }),
    )
    expect(draft.source_run_id).toBeUndefined()
    expect(draft.use_replay_script).toBe(false)
  })

  it('preserves fresh_profile even when Connect tunnel cdp_url is set', () => {
    const draft = toTrainingDraft(
      mockRun({
        run_id: 't1',
        status: 'fail',
        fresh_profile: true,
        cdp_url: 'ws://127.0.0.1:18800/cdp/proxy/abc',
      }),
    )
    expect(draft.fresh_profile).toBe(true)
    expect(draft.cdp_url).toBeUndefined()
  })

  it('preserves fresh_profile false when prior run used a persistent profile', () => {
    const draft = toTrainingDraft(
      mockRun({
        run_id: 't1',
        status: 'fail',
        fresh_profile: false,
        cdp_url: 'ws://127.0.0.1:18800/cdp/proxy/abc',
      }),
    )
    expect(draft.fresh_profile).toBe(false)
    expect(draft.cdp_url).toBeUndefined()
  })

  it('defaults fresh_profile to true when missing', () => {
    const draft = toTrainingDraft(mockRun({ run_id: 't1', status: 'fail' }))
    expect(draft.fresh_profile).toBe(true)
  })
})

describe('toAutomaticDraft', () => {
  it('uses the training run itself when it has a replay', () => {
    const draft = toAutomaticDraft(mockRun({ run_id: 't1', has_replay_script: true }))
    expect(draft).toEqual(
      expect.objectContaining({
        source_run_id: 't1',
        use_replay_script: true,
        run_mode: 'automatic',
      }),
    )
  })

  it('uses source_run_id for automatic runs when source replay is available', () => {
    const draft = toAutomaticDraft(
      mockRun({
        run_id: 'a1',
        use_replay_script: true,
        source_run_id: 't1',
        has_replay_script: true,
      }),
    )
    expect(draft?.source_run_id).toBe('t1')
  })

  it('returns null for orphan automatic without replay', () => {
    expect(
      toAutomaticDraft(
        mockRun({
          run_id: 'a1',
          use_replay_script: true,
          source_run_id: 'deleted',
          has_replay_script: false,
        }),
      ),
    ).toBeNull()
  })

  it('prefers project last_trained_run_id', () => {
    const projects: Project[] = [
      {
        id: 'p1',
        name: 'Proj',
        url: '',
        description: '',
        context_prompt: '',
        tasks: [
          {
            id: 'task-1',
            name: 'Login',
            task: 'Do the thing',
            success_criteria: 'Done',
            headless: false,
            max_steps: 100,
            has_trained_replay: true,
            last_trained_run_id: 'trained-9',
          },
        ],
      },
    ]
    const draft = toAutomaticDraft(
      mockRun({
        run_id: 'a1',
        use_replay_script: true,
        source_run_id: 'old',
        website_id: 'p1',
        website_task_id: 'task-1',
        has_replay_script: false,
      }),
      projects,
    )
    expect(draft?.source_run_id).toBe('trained-9')
  })
})

describe('getPrimaryRunAction', () => {
  it('offers re-run training draft for failed training', () => {
    const action = getPrimaryRunAction(mockRun({ run_id: 't1', status: 'fail' }))
    expect(action.kind).toBe('retry_training')
    expect(action.draft.source_run_id).toBeUndefined()
    expect(action.label).toBe('Re-run')
  })

  it('defaults to automatic for passed training with replay', () => {
    const action = getPrimaryRunAction(
      mockRun({ run_id: 't1', status: 'pass', has_replay_script: true }),
    )
    expect(action.kind).toBe('run_automatic')
    expect(action.label).toBe('Re-run')
  })

  it('defaults to automatic for automatic runs with source replay', () => {
    const action = getPrimaryRunAction(
      mockRun({
        run_id: 'a1',
        use_replay_script: true,
        source_run_id: 't1',
        has_replay_script: true,
      }),
    )
    expect(action.kind).toBe('rerun_automatic')
  })

  it('falls back to training when automatic replay is unavailable', () => {
    const action = getPrimaryRunAction(
      mockRun({
        run_id: 'a1',
        use_replay_script: true,
        source_run_id: 'deleted',
        has_replay_script: false,
      }),
    )
    expect(action.kind).toBe('retry_training')
    expect(action.draft.use_replay_script).toBe(false)
  })
})

describe('manual drafts', () => {
  it('toManualDraft clears the placeholder task and forces headed', () => {
    const draft = toManualDraft(
      mockRun({
        run_id: 'm1',
        task: 'Human demonstration',
        headless: true,
        run_mode: 'manual',
      }),
    )
    expect(draft.run_mode).toBe('manual')
    expect(draft.task).toBe('')
    expect(draft.headless).toBe(false)
    expect(draft.use_replay_script).toBe(false)
  })

  it('retries failed manual as manual', () => {
    const action = getPrimaryRunAction(
      mockRun({ run_id: 'm1', status: 'fail', run_mode: 'manual' }),
    )
    expect(action.kind).toBe('retry_manual')
    expect(action.draft.run_mode).toBe('manual')
  })

  it('defaults passed manual with replay to automatic', () => {
    const action = getPrimaryRunAction(
      mockRun({
        run_id: 'm1',
        status: 'pass',
        run_mode: 'manual',
        has_replay_script: true,
      }),
    )
    expect(action.kind).toBe('run_automatic')
    expect(action.draft.source_run_id).toBe('m1')
  })
})

describe('runSummaryToDraft', () => {
  it('defaults failed training to a training draft without lineage', () => {
    const draft = runSummaryToDraft(mockRun({ run_id: 't1', status: 'fail' }))
    expect(draft.use_replay_script).toBe(false)
    expect(draft.source_run_id).toBeUndefined()
  })
})
