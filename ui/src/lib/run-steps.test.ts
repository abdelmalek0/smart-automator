import { describe, expect, it } from 'vitest'
import { isPlaceholderThought, stepDisplayTitle, stepIntent, upsertStep } from './run-steps'
import type { Step } from '@/types'

function step(overrides: Partial<Step> = {}): Step {
  return {
    index: 1,
    thought: '',
    action: 'go_to_url',
    args: {},
    result: '',
    status: 'pass',
    screenshot_url: null,
    elapsed_ms: 0,
    ...overrides,
  }
}

describe('stepDisplayTitle', () => {
  it('uses thought as the training title', () => {
    expect(stepDisplayTitle(step({ thought: 'Log in', action: 'go_to_url' }))).toBe('Log in')
  })

  it('falls back to the action for placeholder training thoughts', () => {
    expect(stepDisplayTitle(step({ thought: 'Observing page and choosing actions…' }))).toBe(
      'go_to_url',
    )
  })

  it('uses thought as the replay title when there is no intent', () => {
    expect(
      stepDisplayTitle(
        step({
          thought: 'Human clicked Select Employee',
          action: 'click_element',
          args: {},
        }),
        { replay: true },
      ),
    ).toBe('Human clicked Select Employee')
  })

  it('prefers intent over thought during agent replay', () => {
    expect(
      stepDisplayTitle(
        step({
          thought: 'Replay step 1',
          action: 'click_element',
          args: { click_element: { index: 2, intent: 'Submit' } },
        }),
        { replay: true },
      ),
    ).toBe('Submit')
  })

  it('skips placeholder replay thoughts', () => {
    expect(
      stepDisplayTitle(step({ thought: 'Replay step 1', action: 'go_to_url' }), { replay: true }),
    ).toBe('go_to_url')
  })
})

describe('stepIntent', () => {
  it('reads nested and batched intents', () => {
    expect(stepIntent({ intent: 'Open link' })).toBe('Open link')
    expect(stepIntent({ click_element: { index: 2, intent: 'Submit' } })).toBe('Submit')
    expect(
      stepIntent({
        actions: [
          { input_text: { index: 0, intent: 'username' } },
          { click_element: { index: 1, intent: 'Submit' } },
        ],
      }),
    ).toBe('username, Submit')
  })
})

describe('isPlaceholderThought', () => {
  it('detects replay numbering', () => {
    expect(isPlaceholderThought('Replay step 12')).toBe(true)
    expect(isPlaceholderThought('Click submit')).toBe(false)
  })
})

describe('upsertStep', () => {
  it('replaces an existing index', () => {
    const next = upsertStep([step({ thought: 'a' })], step({ thought: 'b' }))
    expect(next).toHaveLength(1)
    expect(next[0].thought).toBe('b')
  })
})
