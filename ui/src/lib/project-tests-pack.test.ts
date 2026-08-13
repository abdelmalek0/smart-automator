import { describe, expect, it } from 'vitest'
import {
  buildProjectTestsPack,
  parseProjectTestsPack,
  PROJECT_TESTS_PACK_KIND,
  PROJECT_TESTS_PACK_VERSION,
  projectTestsFilename,
} from '@/lib/project-tests-pack'
import type { ProjectTask } from '@/types'

function task(overrides: Partial<ProjectTask> = {}): ProjectTask {
  return {
    id: 'task-1',
    name: 'Login',
    task: 'Sign in',
    success_criteria: 'Dashboard visible',
    headless: true,
    max_steps: 12,
    last_trained_run_id: 'run-9',
    has_trained_replay: true,
    ...overrides,
  }
}

describe('buildProjectTestsPack', () => {
  it('copies title, task, and criteria only', () => {
    const pack = buildProjectTestsPack([task(), task({ id: 't2', name: '  ' })])
    expect(pack).toEqual({
      version: PROJECT_TESTS_PACK_VERSION,
      kind: PROJECT_TESTS_PACK_KIND,
      tests: [
        { name: 'Login', task: 'Sign in', success_criteria: 'Dashboard visible' },
        { task: 'Sign in', success_criteria: 'Dashboard visible' },
      ],
    })
  })
})

describe('parseProjectTestsPack', () => {
  it('accepts a valid pack and ignores extra fields', () => {
    const pack = parseProjectTestsPack({
      version: 1,
      kind: PROJECT_TESTS_PACK_KIND,
      extra: true,
      tests: [
        {
          id: 'old-id',
          name: 'Login',
          task: ' Sign in ',
          success_criteria: ' Dashboard visible ',
          headless: true,
        },
      ],
    })
    expect(pack.tests).toEqual([
      { name: 'Login', task: 'Sign in', success_criteria: 'Dashboard visible' },
    ])
  })

  it('rejects wrong kind, empty packs, and missing fields', () => {
    expect(() => parseProjectTestsPack({ version: 1, kind: 'nope', tests: [] })).toThrow(
      /not a project tests export/,
    )
    expect(() =>
      parseProjectTestsPack({ version: 1, kind: PROJECT_TESTS_PACK_KIND, tests: [] }),
    ).toThrow(/No tests found/)
    expect(() =>
      parseProjectTestsPack({
        version: 1,
        kind: PROJECT_TESTS_PACK_KIND,
        tests: [{ success_criteria: 'ok' }],
      }),
    ).toThrow(/missing a task/)
  })
})

describe('projectTestsFilename', () => {
  it('slugifies the project name', () => {
    expect(projectTestsFilename('My Shop!')).toBe('my-shop-tests.json')
    expect(projectTestsFilename('   ')).toBe('test-tests.json')
  })

  it('includes the test name when exporting a single test', () => {
    expect(projectTestsFilename('My Shop', 'Login Flow')).toBe('my-shop-login-flow-tests.json')
  })
})
