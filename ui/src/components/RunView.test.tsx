// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import RunView from './RunView'
import type { RunDetails } from '@/types'

beforeAll(() => {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  Element.prototype.scrollIntoView = vi.fn()
})

const taskText = 'Open the shop, add a widget to the cart, then check out.'
const criteriaText = 'Cart shows one widget and checkout succeeds.'

function mockRun(partial: Partial<RunDetails> = {}): RunDetails {
  return {
    run_id: 'run-abcd1234',
    name: 'Checkout smoke',
    task: taskText,
    success_criteria: criteriaText,
    status: 'pass',
    step_count: 0,
    started_at: 100,
    finished_at: 200,
    summary: '',
    tokens: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    cache_tokens: 0,
    cost_usd: null,
    steps: [],
    plan: {},
    new_tools: [],
    run_mode: 'training',
    ...partial,
  }
}

vi.mock('@/hooks/useRunStream', () => ({
  useRunStream: () => ({
    run: mockRun(),
    connected: true,
    closed: true,
    error: null,
    reportReady: true,
  }),
}))

vi.mock('@/api', () => ({
  listProjects: vi.fn().mockResolvedValue([]),
  listRuns: vi.fn().mockResolvedValue([]),
  cancelRun: vi.fn(),
  finishManual: vi.fn(),
  returnControl: vi.fn(),
  takeControl: vi.fn(),
}))

vi.mock('@/contexts/RunModalContext', () => ({
  useRunModal: () => ({ openNewRun: vi.fn(), closeNewRun: vi.fn() }),
}))

function renderView() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RunView runId="run-abcd1234" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RunView', () => {
  afterEach(() => {
    cleanup()
  })

  it('shows the goal and keeps the task collapsed under Description', () => {
    renderView()

    expect(screen.getByRole('heading', { name: 'Checkout smoke' })).toBeTruthy()
    expect(screen.getByText('Goal')).toBeTruthy()
    expect(screen.getByText(criteriaText)).toBeTruthy()
    const trigger = screen.getByRole('button', { name: /description/i })
    expect(trigger).toBeTruthy()
    expect(trigger.getAttribute('data-state')).toBe('closed')
    expect(screen.queryByText(taskText)).toBeNull()

    fireEvent.click(trigger)

    expect(trigger.getAttribute('data-state')).toBe('open')
    expect(screen.getByText(taskText)).toBeTruthy()
  })
})
