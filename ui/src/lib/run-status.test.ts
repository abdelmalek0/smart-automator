import { describe, expect, it } from 'vitest'
import {
  aggregateTurnTiming,
  aggregateTypicalActMs,
  median,
} from './run-status'
import type { Step } from '@/types'

function agentStep(
  index: number,
  elapsed_ms: number,
  turn_timing: Step['turn_timing'],
  source?: Step['source'],
): Step {
  return {
    index,
    thought: 'test',
    action: 'click',
    args: {},
    result: 'ok',
    status: 'pass',
    screenshot_url: null,
    elapsed_ms,
    turn_timing,
    source,
  }
}

describe('median', () => {
  it('returns 0 for empty input', () => {
    expect(median([])).toBe(0)
  })

  it('returns middle value for odd length', () => {
    expect(median([100, 300, 200])).toBe(200)
  })

  it('returns average of middle pair for even length', () => {
    expect(median([100, 400, 200, 300])).toBe(250)
  })
})

describe('aggregateTurnTiming', () => {
  it('returns null when no timed agent steps exist', () => {
    expect(aggregateTurnTiming([])).toBeNull()
    expect(
      aggregateTurnTiming([
        agentStep(1, 1000, { snapshot_ms: 100, llm_navigator_ms: 200 }, 'human'),
      ]),
    ).toBeNull()
    expect(aggregateTurnTiming([agentStep(1, 1000, null)])).toBeNull()
  })

  it('aggregates medians across timed agent steps', () => {
    const steps = [
      agentStep(1, 1000, {
        snapshot_ms: 100,
        llm_navigator_ms: 400,
        batch_ms: 50,
        settle_ms: 10,
      }),
      agentStep(2, 3000, {
        snapshot_ms: 200,
        llm_navigator_ms: 800,
        batch_ms: 150,
        settle_ms: 30,
      }),
      agentStep(3, 2000, {
        snapshot_ms: 150,
        llm_navigator_ms: 600,
        batch_ms: 100,
        settle_ms: 20,
      }),
    ]

    const timing = aggregateTurnTiming(steps)
    expect(timing).toEqual({
      turn_ms: 2000,
      snapshot_ms: 150,
      llm_navigator_ms: 600,
      batch_ms: 100,
      settle_ms: 20,
    })
    expect(aggregateTypicalActMs(steps)).toBe(1250)
  })

  it('excludes human steps from aggregation', () => {
    const steps = [
      agentStep(1, 1000, { snapshot_ms: 100, llm_navigator_ms: 200 }),
      agentStep(2, 9000, { snapshot_ms: 900, llm_navigator_ms: 8000 }, 'human'),
    ]

    const timing = aggregateTurnTiming(steps)
    expect(timing?.turn_ms).toBe(1000)
    expect(timing?.snapshot_ms).toBe(100)
    expect(timing?.llm_navigator_ms).toBe(200)
  })
})
