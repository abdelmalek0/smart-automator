import type { Step } from '@/types'

const PLACEHOLDER_THOUGHTS = new Set([
  'observing page and choosing actions…',
  'observing page and choosing actions...',
  'replaying recorded actions…',
  'replaying recorded actions...',
  'human intervention',
])

export function isPlaceholderThought(thought: string): boolean {
  const text = thought.trim().toLowerCase()
  if (!text || PLACEHOLDER_THOUGHTS.has(text)) return true
  if (/^replay step \d+$/.test(text)) return true
  return text.startsWith('replay:')
}

function firstString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** Pull `intent` from replay/action args (top-level, nested action, or batch). */
export function stepIntent(args: Record<string, unknown> | undefined): string {
  if (!args) return ''
  const direct = firstString(args.intent)
  if (direct) return direct
  for (const value of Object.values(args)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const nested = firstString((value as Record<string, unknown>).intent)
      if (nested) return nested
    }
  }
  const actions = args.actions
  if (!Array.isArray(actions)) return ''
  const intents: string[] = []
  for (const item of actions) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    for (const inner of Object.values(item as Record<string, unknown>)) {
      if (!inner || typeof inner !== 'object' || Array.isArray(inner)) continue
      const intent = firstString((inner as Record<string, unknown>).intent)
      if (intent) intents.push(intent)
    }
  }
  if (intents.length === 1) return intents[0]
  if (intents.length > 1) return intents.join(', ')
  return ''
}

/** Training: subtitle (`thought`). Replay: `intent`, else `thought`, else action. */
export function stepDisplayTitle(
  step: Pick<Step, 'thought' | 'action' | 'args' | 'result'>,
  opts?: { replay?: boolean },
): string {
  const thought = (step.thought || '').trim()
  const meaningfulThought = thought && !isPlaceholderThought(thought) ? thought : ''
  if (opts?.replay) {
    const label = firstString(step.args?.label)
    const result = (step.result || '').trim()
    return stepIntent(step.args) || meaningfulThought || label || result || (step.action || '').trim()
  }
  return meaningfulThought || (step.action || thought).trim()
}

/** Insert or replace a step and keep the timeline ordered by index. */
export function upsertStep(steps: Step[], step: Step): Step[] {
  const exists = steps.some((s) => s.index === step.index)
  const next = exists
    ? steps.map((s) => (s.index === step.index ? step : s))
    : [...steps, step]
  return [...next].sort((a, b) => a.index - b.index)
}
