// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import NewRunModal from './NewRunModal'
import { getRun } from '@/api'
import type { RunDraft, RunDetails } from '@/types'

beforeAll(() => {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  Element.prototype.scrollIntoView = vi.fn()
})

vi.mock('@/hooks/useRunStartGate', () => ({
  useRunStartGate: () => ({
    canStartRun: true,
    blockReason: null,
    blockHint: null,
  }),
}))

vi.mock('@/hooks/useProjects', () => ({
  useProjects: () => ({
    projects: [{ id: 'proj-1', name: 'Demo site', tasks: [] }],
    addTaskToProject: vi.fn(),
  }),
}))

vi.mock('@/api', () => ({
  getConfig: vi.fn().mockResolvedValue({ fresh_profile: true }),
  listProjects: vi.fn().mockResolvedValue([{ id: 'proj-1', name: 'Demo site', tasks: [] }]),
  getRun: vi.fn(),
  startRun: vi.fn(),
}))

const trainingDraft: RunDraft = {
  name: 'Checkout smoke',
  task: 'Add item to cart',
  success_criteria: 'Cart shows one item',
  website_id: 'proj-1',
  headless: false,
  fresh_profile: true,
  max_steps: 100,
  run_mode: 'training',
  use_replay_script: false,
}

function renderModal(initialValues?: RunDraft) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NewRunModal onClose={() => {}} initialValues={initialValues} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('NewRunModal', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the full new-run form', () => {
    renderModal()

    expect(screen.getByRole('heading', { name: 'New QA Run' })).toBeTruthy()
    expect(screen.getByLabelText(/test task/i)).toBeTruthy()
    expect(screen.getByLabelText(/success criteria/i)).toBeTruthy()
    expect(screen.queryByLabelText(/^title$/i)).toBeNull()
    expect(screen.getByRole('button', { name: 'Advanced' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }))
    expect(screen.getByLabelText(/max steps/i)).toBeTruthy()
  })

  it('hides max steps on new run when manual mode is selected', () => {
    renderModal()

    fireEvent.click(screen.getByRole('button', { name: 'Manual' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }))

    expect(screen.queryByLabelText(/max steps/i)).toBeNull()
  })

  it('shows the short re-run form with locked title and project', () => {
    renderModal(trainingDraft)

    expect(screen.getByRole('heading', { name: 'Re-run QA Test' })).toBeTruthy()
    const project = screen.getByLabelText(/^project$/i)
    const title = screen.getByLabelText(/^title$/i)
    expect(project.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(title).toHaveProperty('disabled', true)
    expect(title).toHaveProperty('value', 'Checkout smoke')
    expect(project).toHaveProperty('disabled', true)
    expect(project).toHaveProperty('value', 'Demo site')
    expect(screen.queryByLabelText(/test task/i)).toBeNull()
    expect(screen.queryByLabelText(/success criteria/i)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Advanced' })).toBeNull()
    expect(screen.getByLabelText(/max steps/i)).toBeTruthy()
  })

  it('hides max steps on re-run when manual mode is selected', () => {
    renderModal(trainingDraft)

    fireEvent.click(screen.getByRole('button', { name: 'Manual' }))

    expect(screen.queryByLabelText(/max steps/i)).toBeNull()
    expect(screen.getByLabelText(/headless/i)).toHaveProperty('disabled', true)
  })

  it('hides max steps on re-run when automatic mode is selected', async () => {
    vi.mocked(getRun).mockResolvedValue({
      run_id: 'source-run-1',
      task: 'Add item to cart',
      success_criteria: 'Cart shows one item',
      status: 'pass',
      use_replay_script: false,
      has_replay_script: true,
      step_count: 1,
      started_at: 0,
      finished_at: 1,
      summary: '',
      tokens: 0,
      steps: [],
      plan: {},
      new_tools: [],
      prompt_tokens: 0,
      completion_tokens: 0,
      cache_tokens: 0,
      cost_usd: null,
    } satisfies RunDetails)
    const automaticDraft: RunDraft = {
      ...trainingDraft,
      run_mode: 'automatic',
      use_replay_script: true,
      source_run_id: 'source-run-1',
    }
    renderModal(automaticDraft)

    await waitFor(() => {
      expect(screen.queryByLabelText(/max steps/i)).toBeNull()
    })
  })
})
