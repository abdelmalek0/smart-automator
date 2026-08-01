import { describe, expect, it } from 'vitest'
import {
  computeProjectMetrics,
  filterAndSortProjects,
  filterProjects,
  filterProjectsByTab,
  getProjectCardStats,
  projectInitials,
  projectListMeta,
  sortProjects,
} from '@/lib/project-view'
import type { Project } from '@/types'

function task(
  id: string,
  opts: { name?: string; task?: string; trained?: boolean } = {},
): Project['tasks'][number] {
  return {
    id,
    name: opts.name ?? null,
    task: opts.task ?? `Do ${id}`,
    success_criteria: 'ok',
    headless: false,
    max_steps: 50,
    has_trained_replay: opts.trained ?? false,
    last_trained_run_id: opts.trained ? `run-${id}` : null,
  }
}

function project(
  id: string,
  opts: Partial<Project> & { name: string },
): Project {
  return {
    id,
    name: opts.name,
    url: opts.url ?? '',
    description: opts.description ?? '',
    context_prompt: opts.context_prompt ?? '',
    tasks: opts.tasks ?? [],
  }
}

describe('projectInitials', () => {
  it('uses first two letters for a single word', () => {
    expect(projectInitials('Checkout')).toBe('CH')
  })

  it('uses first letters of two words', () => {
    expect(projectInitials('Acme Store')).toBe('AS')
  })

  it('handles empty names', () => {
    expect(projectInitials('   ')).toBe('?')
  })
})

describe('getProjectCardStats', () => {
  it('counts tests, trained, and configuration', () => {
    const stats = getProjectCardStats(
      project('p1', {
        name: 'Demo',
        url: 'https://example.com',
        context_prompt: 'notes',
        tasks: [task('t1', { trained: true }), task('t2')],
      }),
    )
    expect(stats).toMatchObject({
      testCount: 2,
      trainedCount: 1,
      hasUrl: true,
      hasNotes: true,
      isConfigured: true,
      initials: 'DE',
    })
  })
})

describe('computeProjectMetrics', () => {
  it('aggregates coverage across projects', () => {
    const metrics = computeProjectMetrics([
      project('a', {
        name: 'A',
        url: 'https://a.test',
        tasks: [task('1', { trained: true }), task('2')],
      }),
      project('b', {
        name: 'B',
        tasks: [task('3')],
      }),
    ])
    expect(metrics).toEqual({
      projectCount: 2,
      testCount: 3,
      trainedCount: 1,
      trainedCoverage: 33,
      configuredCount: 1,
    })
  })

  it('returns zero coverage with no tests', () => {
    expect(computeProjectMetrics([project('a', { name: 'A' })]).trainedCoverage).toBe(0)
  })
})

describe('filterProjects', () => {
  const sample = [
    project('1', {
      name: 'Checkout',
      url: 'https://shop.example',
      tasks: [task('t1', { name: 'Pay', task: 'Complete payment' })],
    }),
    project('2', {
      name: 'Admin',
      context_prompt: 'staging credentials',
      tasks: [task('t2', { task: 'Invite user' })],
    }),
  ]

  it('matches project name, description, url, notes, and task text', () => {
    const withDesc = [
      ...sample,
      project('3', { name: 'Billing', description: 'Invoice regression suite' }),
    ]
    expect(filterProjects(sample, 'check').map((p) => p.id)).toEqual(['1'])
    expect(filterProjects(withDesc, 'invoice').map((p) => p.id)).toEqual(['3'])
    expect(filterProjects(sample, 'shop.example').map((p) => p.id)).toEqual(['1'])
    expect(filterProjects(sample, 'staging').map((p) => p.id)).toEqual(['2'])
    expect(filterProjects(sample, 'invite').map((p) => p.id)).toEqual(['2'])
    expect(filterProjects(sample, 'pay').map((p) => p.id)).toEqual(['1'])
  })

  it('returns all projects for blank query', () => {
    expect(filterProjects(sample, '  ')).toHaveLength(2)
  })
})

describe('filterProjectsByTab', () => {
  const sample = [
    project('empty', { name: 'Empty' }),
    project('tests', { name: 'Has tests', tasks: [task('t1')] }),
    project('trained', {
      name: 'Trained',
      tasks: [task('t2', { trained: true })],
    }),
  ]

  it('returns all projects for all', () => {
    expect(filterProjectsByTab(sample, 'all')).toHaveLength(3)
  })

  it('filters projects with tests', () => {
    expect(filterProjectsByTab(sample, 'with-tests').map((p) => p.id)).toEqual([
      'tests',
      'trained',
    ])
  })

  it('filters trained projects', () => {
    expect(filterProjectsByTab(sample, 'trained').map((p) => p.id)).toEqual(['trained'])
  })
})

describe('projectListMeta', () => {
  it('formats empty, tests-only, and trained labels', () => {
    expect(projectListMeta(project('a', { name: 'A' }))).toBe('No tests')
    expect(projectListMeta(project('b', { name: 'B', tasks: [task('1'), task('2')] }))).toBe(
      '2 tests',
    )
    expect(
      projectListMeta(
        project('c', {
          name: 'C',
          tasks: [task('1', { trained: true }), task('2')],
        }),
      ),
    ).toBe('2 tests · 1 trained')
  })
})

describe('sortProjects', () => {
  const sample = [
    project('a', {
      name: 'Beta',
      tasks: [task('1'), task('2', { trained: true })],
    }),
    project('b', {
      name: 'Alpha',
      tasks: [task('3', { trained: true }), task('4', { trained: true }), task('5')],
    }),
  ]

  it('sorts by name ascending and descending', () => {
    expect(sortProjects(sample, 'name-asc').map((p) => p.name)).toEqual(['Alpha', 'Beta'])
    expect(sortProjects(sample, 'name-desc').map((p) => p.name)).toEqual(['Beta', 'Alpha'])
  })

  it('sorts by test count', () => {
    expect(sortProjects(sample, 'tests-desc').map((p) => p.id)).toEqual(['b', 'a'])
    expect(sortProjects(sample, 'tests-asc').map((p) => p.id)).toEqual(['a', 'b'])
  })

  it('sorts by trained count', () => {
    expect(sortProjects(sample, 'trained-desc').map((p) => p.id)).toEqual(['b', 'a'])
  })
})

describe('filterAndSortProjects', () => {
  it('filters then sorts', () => {
    const sample = [
      project('1', { name: 'Shop A', tasks: [task('t1'), task('t2')] }),
      project('2', { name: 'Shop B', tasks: [task('t3')] }),
      project('3', { name: 'Other', tasks: [task('t4'), task('t5'), task('t6')] }),
    ]
    expect(filterAndSortProjects(sample, 'shop', 'tests-desc').map((p) => p.id)).toEqual([
      '1',
      '2',
    ])
  })

  it('applies tab filter before search', () => {
    const sample = [
      project('1', { name: 'Shop empty' }),
      project('2', { name: 'Shop ready', tasks: [task('t1', { trained: true })] }),
    ]
    expect(
      filterAndSortProjects(sample, 'shop', 'name-asc', 'trained').map((p) => p.id),
    ).toEqual(['2'])
  })
})
