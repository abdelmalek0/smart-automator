import type { RunMode } from '@/types'

/** Whether the max-steps control appears for a run mode. */
export function runModeShowsMaxSteps(runMode: RunMode): boolean {
  return runMode === 'training'
}

export function rerunTitleLabel(name: string | undefined): string {
  return name?.trim() || 'Untitled'
}

export function rerunProjectLabel(
  projectId: string | undefined,
  projectName: string | undefined,
): string {
  if (!projectId) return 'No project'
  return projectName ?? 'Unknown project'
}
