import type { Step } from '@/types'

/** Insert or replace a step and keep the timeline ordered by index. */
export function upsertStep(steps: Step[], step: Step): Step[] {
  const exists = steps.some((s) => s.index === step.index)
  const next = exists
    ? steps.map((s) => (s.index === step.index ? step : s))
    : [...steps, step]
  return [...next].sort((a, b) => a.index - b.index)
}
