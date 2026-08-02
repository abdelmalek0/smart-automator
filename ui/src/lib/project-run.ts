import { getRun, startRun } from '@/api'
import type { Project, ProjectTask, RunSummary } from '@/types'

export type StartRunPayload = Parameters<typeof startRun>[0]

export type BuildStartRunPayloadOptions = {
  forceTraining?: boolean
}

/** Build POST /api/runs payload for a project test (automatic when trained). */
export function buildStartRunPayload(
  project: Project,
  task: ProjectTask,
  options: BuildStartRunPayloadOptions = {},
): StartRunPayload {
  const canAutomatic =
    !options.forceTraining && Boolean(task.has_trained_replay && task.last_trained_run_id)
  return {
    name: task.name ?? undefined,
    task: task.task,
    success_criteria: task.success_criteria,
    headless: task.headless,
    max_steps: task.max_steps,
    cdp_url: task.cdp_url,
    fresh_profile: task.fresh_profile ?? true,
    website_id: project.id,
    website_task_id: task.id,
    ...(canAutomatic
      ? {
          source_run_id: task.last_trained_run_id!,
          use_replay_script: true,
        }
      : { use_replay_script: false }),
  }
}

export const TERMINAL_RUN_STATUSES = new Set(['pass', 'fail', 'error', 'cancelled'])

export function isTerminalRunStatus(status: string | undefined | null): boolean {
  return Boolean(status && TERMINAL_RUN_STATUSES.has(status))
}

export type WaitForRunOptions = {
  intervalMs?: number
  signal?: AbortSignal
}

/** Poll getRun until the run reaches a terminal status (or abort). */
export async function waitForRunTerminal(
  runId: string,
  options: WaitForRunOptions = {},
): Promise<RunSummary> {
  const intervalMs = options.intervalMs ?? 1200
  const { signal } = options

  for (;;) {
    if (signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError')
    }
    const run = await getRun(runId)
    if (isTerminalRunStatus(run.status)) {
      return run
    }
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, intervalMs)
      const onAbort = () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      }
      if (signal) {
        if (signal.aborted) {
          clearTimeout(timer)
          reject(new DOMException('Aborted', 'AbortError'))
          return
        }
        signal.addEventListener('abort', onAbort, { once: true })
      }
    })
  }
}

export async function startProjectTaskRun(
  project: Project,
  task: ProjectTask,
  options: BuildStartRunPayloadOptions = {},
): Promise<RunSummary> {
  return startRun(buildStartRunPayload(project, task, options))
}
