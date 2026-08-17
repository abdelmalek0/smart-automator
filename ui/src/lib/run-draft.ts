import type { Project, RunDraft, RunSummary } from '@/types'
import { canRunUseAutomatic, isManualRun, MANUAL_PLACEHOLDER_TASK } from '@/lib/run-status'

function baseDraft(run: RunSummary): RunDraft {
  return {
    name: run.name ?? undefined,
    task: run.task,
    success_criteria: run.success_criteria,
    website_id: run.website_id ?? undefined,
    website_task_id: run.website_task_id ?? undefined,
    headless: run.headless ?? false,
    max_steps: run.max_steps ?? 100,
    fresh_profile: run.fresh_profile ?? true,
  }
}

function projectTaskSource(run: RunSummary, projects?: Project[]): string | undefined {
  if (!projects || !run.website_id || !run.website_task_id) return undefined
  const project = projects.find((p) => p.id === run.website_id)
  const task = project?.tasks.find((t) => t.id === run.website_task_id)
  if (task?.has_trained_replay && task.last_trained_run_id) {
    return task.last_trained_run_id
  }
  return undefined
}

/** Training draft never submits source_run_id; may include it so the modal can offer Automatic. */
export function toTrainingDraft(run: RunSummary, projects?: Project[]): RunDraft {
  const autoSource = resolveAutomaticSourceRunId(run, projects)
  return {
    ...baseDraft(run),
    use_replay_script: false,
    run_mode: 'training',
    ...(autoSource ? { source_run_id: autoSource } : {}),
  }
}

/** Resolve the training run id whose replay should be used for automatic execution. */
export function resolveAutomaticSourceRunId(
  run: RunSummary,
  projects?: Project[],
): string | undefined {
  const fromTask = projectTaskSource(run, projects)
  if (fromTask) return fromTask

  if (!run.use_replay_script && canRunUseAutomatic(run)) {
    return run.run_id
  }

  if (run.use_replay_script && run.source_run_id && run.has_replay_script) {
    return run.source_run_id
  }

  return undefined
}

export function toAutomaticDraft(run: RunSummary, projects?: Project[]): RunDraft | null {
  const sourceRunId = resolveAutomaticSourceRunId(run, projects)
  if (!sourceRunId) return null

  let websiteTaskId = run.website_task_id ?? undefined
  if (projects && run.website_id && run.website_task_id) {
    const project = projects.find((p) => p.id === run.website_id)
    const task = project?.tasks.find((t) => t.id === run.website_task_id)
    if (task) websiteTaskId = task.id
  }

  return {
    ...baseDraft(run),
    website_task_id: websiteTaskId,
    source_run_id: sourceRunId,
    use_replay_script: true,
    run_mode: 'automatic',
  }
}

export function toManualDraft(run: RunSummary): RunDraft {
  return {
    ...baseDraft(run),
    task: run.task === MANUAL_PLACEHOLDER_TASK ? '' : run.task,
    use_replay_script: false,
    run_mode: 'manual',
    headless: false,
  }
}

export type PrimaryRunAction =
  | { kind: 'run_automatic'; label: string; draft: RunDraft }
  | { kind: 'rerun_automatic'; label: string; draft: RunDraft }
  | { kind: 'retry_training'; label: string; draft: RunDraft }
  | { kind: 'retry_manual'; label: string; draft: RunDraft }

function isFailedOrUnfinishedAuthored(run: RunSummary): boolean {
  if (run.use_replay_script) return false
  return run.status !== 'pass'
}

/**
 * Opens the Re-run modal with a sensible default mode.
 * User can still switch Training / Manual / Automatic in the modal.
 */
export function getPrimaryRunAction(
  run: RunSummary,
  projects?: Project[],
): PrimaryRunAction {
  if (run.use_replay_script) {
    const draft = toAutomaticDraft(run, projects)
    if (draft) return { kind: 'rerun_automatic', label: 'Re-run', draft }
    return { kind: 'retry_training', label: 'Re-run', draft: toTrainingDraft(run, projects) }
  }

  if (isFailedOrUnfinishedAuthored(run)) {
    if (isManualRun(run)) {
      return { kind: 'retry_manual', label: 'Re-run', draft: toManualDraft(run) }
    }
    return { kind: 'retry_training', label: 'Re-run', draft: toTrainingDraft(run, projects) }
  }

  const auto = toAutomaticDraft(run, projects)
  if (auto) {
    return { kind: 'run_automatic', label: 'Re-run', draft: auto }
  }

  if (isManualRun(run)) {
    return { kind: 'retry_manual', label: 'Re-run', draft: toManualDraft(run) }
  }

  return { kind: 'retry_training', label: 'Re-run', draft: toTrainingDraft(run, projects) }
}

/**
 * Default draft when opening the modal from a generic entry point.
 * Prefers automatic when available; otherwise training without lineage.
 */
export function runSummaryToDraft(run: RunSummary, projects?: Project[]): RunDraft {
  return getPrimaryRunAction(run, projects).draft
}
