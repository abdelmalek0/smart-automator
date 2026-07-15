import type { RunDraft, RunSummary } from '@/types'

export function runSummaryToDraft(run: RunSummary): RunDraft {
  return {
    task: run.task,
    website_id: run.website_id ?? undefined,
    headless: run.headless ?? false,
    max_steps: run.max_steps ?? 100,
    cdp_url: run.cdp_url ?? undefined,
    fresh_profile: run.fresh_profile ?? false,
  }
}
