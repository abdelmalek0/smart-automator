import { describe, expect, it } from 'vitest'
import {
  buildProjectPack,
  parseProjectPack,
  PROJECT_PACK_KIND,
  PROJECT_PACK_VERSION,
  projectPackFilename,
} from '@/lib/project-pack'
import { PROJECT_TESTS_PACK_KIND } from '@/lib/project-tests-pack'
import type { Project } from '@/types'

function project(overrides: Partial<Project> = {}): Project {
  return {
    id: 'proj-1',
    name: 'My Shop',
    description: 'Checkout flows',
    url: 'https://shop.example.com',
    context_prompt: 'Use demo account',
    tasks: [
      {
        id: 't1',
        name: 'Login',
        task: 'Sign in',
        success_criteria: 'Dashboard visible',
        headless: false,
        max_steps: 50,
        last_trained_run_id: 'run-1',
        has_trained_replay: true,
      },
    ],
    ...overrides,
  }
}

describe('buildProjectPack', () => {
  it('includes project metadata and test definitions only', () => {
    expect(buildProjectPack(project())).toEqual({
      version: PROJECT_PACK_VERSION,
      kind: PROJECT_PACK_KIND,
      project: {
        name: 'My Shop',
        description: 'Checkout flows',
        url: 'https://shop.example.com',
        context_prompt: 'Use demo account',
      },
      tests: [{ name: 'Login', task: 'Sign in', success_criteria: 'Dashboard visible' }],
    })
  })
})

describe('parseProjectPack', () => {
  it('accepts a valid pack and ignores extra fields', () => {
    const pack = parseProjectPack({
      version: 1,
      kind: PROJECT_PACK_KIND,
      extra: true,
      project: {
        id: 'old-id',
        name: ' Imported ',
        description: 'Notes',
        url: 'https://example.com',
        context_prompt: 'Project context',
      },
      tests: [
        {
          id: 'old-task',
          name: 'Login',
          task: ' Sign in ',
          success_criteria: ' Dashboard visible ',
        },
      ],
    })
    expect(pack.project.name).toBe('Imported')
    expect(pack.tests).toEqual([
      { name: 'Login', task: 'Sign in', success_criteria: 'Dashboard visible' },
    ])
  })

  it('allows empty tests and rejects wrong kinds', () => {
    expect(() =>
      parseProjectPack({
        version: 1,
        kind: PROJECT_PACK_KIND,
        project: { name: 'Demo' },
        tests: [],
      }),
    ).not.toThrow()

    expect(() =>
      parseProjectPack({
        version: 1,
        kind: PROJECT_TESTS_PACK_KIND,
        tests: [{ task: 'x', success_criteria: 'y' }],
      }),
    ).toThrow(/tests only/)
  })
})

describe('projectPackFilename', () => {
  it('slugifies the project name', () => {
    expect(projectPackFilename('My Shop!')).toBe('my-shop.json')
  })
})
