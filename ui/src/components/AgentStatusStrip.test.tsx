// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AgentPhase } from '@/hooks/useRunStartGate'
import type { RunSummary } from '@/types'

const gate = vi.hoisted(() => ({
  agentPhase: 'connected' as AgentPhase,
  activeRun: null as RunSummary | null,
}))

vi.mock('@/hooks/useRunStartGate', () => ({
  useRunStartGate: () => ({
    agentPhase: gate.agentPhase,
    activeRun: gate.activeRun,
  }),
}))

import AgentStatusStrip from './AgentStatusStrip'

afterEach(() => {
  cleanup()
  gate.agentPhase = 'connected'
  gate.activeRun = null
})

const SURFACES: Record<AgentPhase, string> = {
  offline: 'border-destructive/30 bg-destructive/10 text-destructive',
  connected: 'border-success/30 bg-success/10 text-success',
  starting: 'border-warning/30 bg-warning/10 text-warning',
  running: 'border-brand-blue/30 bg-brand-blue/10 text-brand-blue',
  awaiting_human: 'border-warning/30 bg-warning/10 text-warning',
}

const TITLES: Record<AgentPhase, string> = {
  offline: 'Agent is offline',
  connected: 'Agent is connected',
  starting: 'Agent is starting…',
  running: 'Agent is running',
  awaiting_human: 'Agent is recording',
}

describe('AgentStatusStrip', () => {
  it.each(Object.entries(TITLES) as Array<[AgentPhase, string]>)(
    'keeps %s copy and applies the badge surface',
    (phase, title) => {
      gate.agentPhase = phase
      render(<AgentStatusStrip embedded />)
      expect(screen.getByText(title)).toBeTruthy()
      const status = screen.getByRole('status')
      for (const token of SURFACES[phase].split(' ')) {
        expect(status.className).toContain(token)
      }
      expect(status.className).toContain('transition-colors')
      expect(status.className).toContain('duration-300')
    },
  )

  it('keeps the offline connect hint', () => {
    gate.agentPhase = 'offline'
    render(<AgentStatusStrip embedded />)
    expect(screen.getByText('Run the Connect app')).toBeTruthy()
  })
})
