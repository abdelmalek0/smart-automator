import type { RunDraft, RunSummary } from '@/types'

export function runSummaryToDraft(run: RunSummary): RunDraft {
  return {
    name: run.name ?? undefined,
    task: run.task,
    success_criteria: run.success_criteria,
    source_run_id: run.run_id,
    use_replay_script: true,
    website_id: run.website_id ?? undefined,
    headless: run.headless ?? false,
    max_steps: run.max_steps ?? 100,
    cdp_url: run.cdp_url ?? undefined,
    fresh_profile: run.fresh_profile ?? false,
  }
}
