import type { ProjectTask } from '@/types'

export const PROJECT_TESTS_PACK_KIND = 'smart-automator.project-tests'
export const PROJECT_TESTS_PACK_VERSION = 1

export interface ProjectTestExportItem {
  name?: string | null
  task: string
  success_criteria: string
}

export interface ProjectTestsPack {
  version: number
  kind: string
  tests: ProjectTestExportItem[]
}

export function buildProjectTestsPack(tasks: ProjectTask[]): ProjectTestsPack {
  return {
    version: PROJECT_TESTS_PACK_VERSION,
    kind: PROJECT_TESTS_PACK_KIND,
    tests: tasks.map((task) => {
      const item: ProjectTestExportItem = {
        task: task.task,
        success_criteria: task.success_criteria,
      }
      if (task.name?.trim()) {
        item.name = task.name.trim()
      }
      return item
    }),
  }
}

export function parseProjectTestsPack(data: unknown): ProjectTestsPack {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Invalid tests file')
  }
  const raw = data as Record<string, unknown>
  if (raw.kind !== PROJECT_TESTS_PACK_KIND) {
    throw new Error('This file is not a project tests export')
  }
  if (raw.version !== PROJECT_TESTS_PACK_VERSION) {
    throw new Error('Unsupported tests file version')
  }
  if (!Array.isArray(raw.tests) || raw.tests.length === 0) {
    throw new Error('No tests found in this file')
  }
  const tests: ProjectTestExportItem[] = raw.tests.map((entry, index) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      throw new Error(`Test ${index + 1} is invalid`)
    }
    const item = entry as Record<string, unknown>
    const task = typeof item.task === 'string' ? item.task.trim() : ''
    const success_criteria =
      typeof item.success_criteria === 'string' ? item.success_criteria.trim() : ''
    if (!task) {
      throw new Error(`Test ${index + 1} is missing a task`)
    }
    if (!success_criteria) {
      throw new Error(`Test ${index + 1} is missing success criteria`)
    }
    const name = typeof item.name === 'string' && item.name.trim() ? item.name.trim() : undefined
    return name ? { name, task, success_criteria } : { task, success_criteria }
  })
  return {
    version: PROJECT_TESTS_PACK_VERSION,
    kind: PROJECT_TESTS_PACK_KIND,
    tests,
  }
}

export function slugifySegment(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'test'
  )
}

export function projectTestsFilename(projectName: string, taskName?: string | null): string {
  const projectSlug = slugifySegment(projectName) || 'project'
  if (taskName?.trim()) {
    return `${projectSlug}-${slugifySegment(taskName)}-tests.json`
  }
  return `${projectSlug}-tests.json`
}

export function downloadProjectTestsPack(
  projectName: string,
  tasks: ProjectTask[],
  options?: { taskName?: string | null },
): void {
  const pack = buildProjectTestsPack(tasks)
  const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = projectTestsFilename(projectName, options?.taskName)
  anchor.click()
  URL.revokeObjectURL(url)
}
