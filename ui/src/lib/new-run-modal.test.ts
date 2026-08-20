import { describe, expect, it } from 'vitest'
import { rerunProjectLabel, rerunTitleLabel, runModeShowsMaxSteps } from './new-run-modal'

describe('rerunTitleLabel', () => {
  it('uses the test name when present', () => {
    expect(rerunTitleLabel('Checkout smoke')).toBe('Checkout smoke')
  })

  it('falls back to Untitled', () => {
    expect(rerunTitleLabel(undefined)).toBe('Untitled')
    expect(rerunTitleLabel('   ')).toBe('Untitled')
  })
})

describe('rerunProjectLabel', () => {
  it('shows no project when unlinked', () => {
    expect(rerunProjectLabel(undefined, undefined)).toBe('No project')
  })

  it('shows the project name when known', () => {
    expect(rerunProjectLabel('proj-1', 'Demo site')).toBe('Demo site')
  })
})

describe('runModeShowsMaxSteps', () => {
  it('shows max steps only for training', () => {
    expect(runModeShowsMaxSteps('training')).toBe(true)
  })

  it('hides max steps for manual and automatic', () => {
    expect(runModeShowsMaxSteps('manual')).toBe(false)
    expect(runModeShowsMaxSteps('automatic')).toBe(false)
  })
})
