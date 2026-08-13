import type { Project } from '@/types'
import {
  buildProjectTestsPack,
  parseProjectTestsPack,
  PROJECT_TESTS_PACK_KIND,
  type ProjectTestExportItem,
  type ProjectTestsPack,
  slugifySegment,
} from '@/lib/project-tests-pack'

export const PROJECT_PACK_KIND = 'smart-automator.project'
export const PROJECT_PACK_VERSION = 1

export interface ProjectExportData {
  name: string
  description: string
  url: string
  context_prompt: string
}

export interface ProjectPack {
  version: number
  kind: string
  project: ProjectExportData
  tests: ProjectTestExportItem[]
}

export function buildProjectPack(project: Project): ProjectPack {
  return {
    version: PROJECT_PACK_VERSION,
    kind: PROJECT_PACK_KIND,
    project: {
      name: project.name,
      description: project.description ?? '',
      url: project.url ?? '',
      context_prompt: project.context_prompt ?? '',
    },
    tests: buildProjectTestsPack(project.tasks).tests,
  }
}

export function parseProjectPack(data: unknown): ProjectPack {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Invalid project file')
  }
  const raw = data as Record<string, unknown>
  if (raw.kind !== PROJECT_PACK_KIND) {
    if (raw.kind === PROJECT_TESTS_PACK_KIND) {
      throw new Error('This file contains tests only. Import it from a project page.')
    }
    throw new Error('This file is not a project export')
  }
  if (raw.version !== PROJECT_PACK_VERSION) {
    throw new Error('Unsupported project file version')
  }
  if (!raw.project || typeof raw.project !== 'object' || Array.isArray(raw.project)) {
    throw new Error('Project details are missing')
  }
  const projectRaw = raw.project as Record<string, unknown>
  const name = typeof projectRaw.name === 'string' ? projectRaw.name.trim() : ''
  if (!name) {
    throw new Error('Project name is required')
  }
  const description =
    typeof projectRaw.description === 'string' ? projectRaw.description : ''
  const url = typeof projectRaw.url === 'string' ? projectRaw.url : ''
  const context_prompt =
    typeof projectRaw.context_prompt === 'string' ? projectRaw.context_prompt : ''

  let tests: ProjectTestExportItem[] = []
  if (raw.tests !== undefined) {
    if (!Array.isArray(raw.tests)) {
      throw new Error('Tests list is invalid')
    }
    if (raw.tests.length > 0) {
      const testsPack: ProjectTestsPack = parseProjectTestsPack({
        version: PROJECT_PACK_VERSION,
        kind: PROJECT_TESTS_PACK_KIND,
        tests: raw.tests,
      })
      tests = testsPack.tests
    }
  }

  return {
    version: PROJECT_PACK_VERSION,
    kind: PROJECT_PACK_KIND,
    project: { name, description, url, context_prompt },
    tests,
  }
}

export function projectPackFilename(projectName: string): string {
  const slug = slugifySegment(projectName) || 'project'
  return `${slug}.json`
}

export function downloadProjectPack(project: Project): void {
  const pack = buildProjectPack(project)
  const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = projectPackFilename(project.name)
  anchor.click()
  URL.revokeObjectURL(url)
}
