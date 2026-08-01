import type { Project } from '@/types'

export type ProjectSort = 'name-asc' | 'name-desc' | 'tests-desc' | 'tests-asc' | 'trained-desc'

export type ProjectFilter = 'all' | 'with-tests' | 'trained'

export type ProjectMetrics = {
  projectCount: number
  testCount: number
  trainedCount: number
  trainedCoverage: number
  configuredCount: number
}

export type ProjectCardStats = {
  testCount: number
  trainedCount: number
  hasUrl: boolean
  hasNotes: boolean
  isConfigured: boolean
  initials: string
}

export function projectInitials(name: string): string {
  const parts = name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

/** Stable accent index from project id/name for soft avatar colors. */
export function projectAccentIndex(seed: string): number {
  let hash = 0
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }
  return hash % 6
}

export const PROJECT_ACCENT_CLASSES = [
  'bg-primary/15 text-primary',
  'bg-success/15 text-success',
  'bg-warning/15 text-warning',
  'bg-brand-blue/15 text-brand-blue',
  'bg-brand-orange/15 text-brand-orange',
  'bg-secondary text-secondary-foreground',
] as const

export function getProjectCardStats(project: Project): ProjectCardStats {
  const testCount = project.tasks.length
  const trainedCount = project.tasks.filter((t) => t.has_trained_replay).length
  const hasUrl = Boolean(project.url?.trim())
  const hasNotes = Boolean(project.context_prompt?.trim())
  return {
    testCount,
    trainedCount,
    hasUrl,
    hasNotes,
    isConfigured: hasUrl || hasNotes,
    initials: projectInitials(project.name),
  }
}

export function computeProjectMetrics(projects: Project[]): ProjectMetrics {
  const projectCount = projects.length
  let testCount = 0
  let trainedCount = 0
  let configuredCount = 0

  for (const project of projects) {
    const stats = getProjectCardStats(project)
    testCount += stats.testCount
    trainedCount += stats.trainedCount
    if (stats.isConfigured) configuredCount += 1
  }

  return {
    projectCount,
    testCount,
    trainedCount,
    trainedCoverage: testCount === 0 ? 0 : Math.round((trainedCount / testCount) * 100),
    configuredCount,
  }
}

export function filterProjectsByTab(projects: Project[], filter: ProjectFilter): Project[] {
  switch (filter) {
    case 'with-tests':
      return projects.filter((p) => p.tasks.length > 0)
    case 'trained':
      return projects.filter((p) => p.tasks.some((t) => t.has_trained_replay))
    case 'all':
    default:
      return projects
  }
}

export function filterProjects(projects: Project[], query: string): Project[] {
  const q = query.trim().toLowerCase()
  if (!q) return projects
  return projects.filter((project) => {
    if (project.name.toLowerCase().includes(q)) return true
    if (project.description?.toLowerCase().includes(q)) return true
    if (project.url?.toLowerCase().includes(q)) return true
    if (project.context_prompt?.toLowerCase().includes(q)) return true
    return project.tasks.some((task) => {
      const name = (task.name ?? '').toLowerCase()
      return name.includes(q) || task.task.toLowerCase().includes(q)
    })
  })
}

export function sortProjects(projects: Project[], sort: ProjectSort): Project[] {
  const next = [...projects]
  next.sort((a, b) => {
    const aStats = getProjectCardStats(a)
    const bStats = getProjectCardStats(b)
    switch (sort) {
      case 'name-desc':
        return b.name.localeCompare(a.name, undefined, { sensitivity: 'base' })
      case 'tests-desc':
        return bStats.testCount - aStats.testCount || a.name.localeCompare(b.name)
      case 'tests-asc':
        return aStats.testCount - bStats.testCount || a.name.localeCompare(b.name)
      case 'trained-desc':
        return (
          bStats.trainedCount - aStats.trainedCount ||
          bStats.testCount - aStats.testCount ||
          a.name.localeCompare(b.name)
        )
      case 'name-asc':
      default:
        return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
    }
  })
  return next
}

export function filterAndSortProjects(
  projects: Project[],
  query: string,
  sort: ProjectSort,
  filter: ProjectFilter = 'all',
): Project[] {
  return sortProjects(filterProjects(filterProjectsByTab(projects, filter), query), sort)
}

/** Compact secondary label for list rows, e.g. "3 tests · 1 trained". */
export function projectListMeta(project: Project): string {
  const { testCount, trainedCount } = getProjectCardStats(project)
  if (testCount === 0) return 'No tests'
  const tests = `${testCount} test${testCount !== 1 ? 's' : ''}`
  if (trainedCount === 0) return tests
  return `${tests} · ${trainedCount} trained`
}
