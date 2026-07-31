import type { Project, RunDraft, RunSummary } from '@/types'

export function runSummaryToDraft(run: RunSummary, projects?: Project[]): RunDraft {
  const base: RunDraft = {
    name: run.name ?? undefined,
    task: run.task,
    success_criteria: run.success_criteria,
    website_id: run.website_id ?? undefined,
    website_task_id: run.website_task_id ?? undefined,
    headless: run.headless ?? false,
    max_steps: run.max_steps ?? 100,
    cdp_url: run.cdp_url ?? undefined,
    fresh_profile: run.cdp_url?.trim() ? false : (run.fresh_profile ?? true),
  }

  let sourceRunId = run.run_id
  let useReplayScript = true
  let websiteTaskId = run.website_task_id ?? undefined

  if (projects && run.website_id && run.website_task_id) {
    const project = projects.find((p) => p.id === run.website_id)
    const task = project?.tasks.find((t) => t.id === run.website_task_id)
    if (task?.has_trained_replay && task.last_trained_run_id) {
      sourceRunId = task.last_trained_run_id
      useReplayScript = true
      websiteTaskId = task.id
    }
  }

  return {
    ...base,
    website_task_id: websiteTaskId,
    source_run_id: sourceRunId,
    use_replay_script: useReplayScript,
  }
}
