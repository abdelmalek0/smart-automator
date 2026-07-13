import { useEffect, useReducer, useRef } from 'react'
import type { AtomicStep, Plan, RunDetails, RunProgress, Step, WSEvent } from '../types'

interface StreamState {
  run: RunDetails | null
  connected: boolean
  closed: boolean
  error: string | null
  reportReady: boolean
  reportPath: string | null
}

type Action =
  | { type: 'SNAPSHOT'; run: RunDetails }
  | { type: 'STEP_START'; step: Step }
  | { type: 'STEP_END'; step: Step }
  | { type: 'PLAN_UPDATE'; plan: Plan }
  | { type: 'STEPS_EXTRACTED'; steps: AtomicStep[] }
  | { type: 'MILESTONES_UPDATED'; steps: AtomicStep[]; progress?: RunProgress }
  | { type: 'ATOMIC_STEP_FOCUS'; step: number; total: number; atomic: AtomicStep }
  | { type: 'ATOMIC_STEP_DONE'; step: number; progress?: RunProgress }
  | { type: 'VALIDATION_BLOCKED'; atomicStep?: number | null; message: string; progress?: RunProgress }
  | { type: 'VALIDATION_PASSED'; atomicStep?: number | null; message: string; progress?: RunProgress }
  | { type: 'ATOMIC_STEP_COMPLETED'; atomicStep?: number | null; message: string; progress?: RunProgress }
  | { type: 'RUN_FINISHED'; status: string; summary: string; progress?: RunProgress }
  | { type: 'REPORT_READY'; reportPath: string }
  | { type: 'TOOL_WRITTEN'; name: string }
  | { type: 'DONE'; status: string; summary: string }
  | { type: 'STATUS'; status: string }
  | { type: 'TOKENS_UPDATE'; tokens: number; prompt_tokens: number; completion_tokens: number; cache_tokens: number; cost_usd: number | null }
  | { type: 'TURN_TIMING'; snapshot_ms?: number; llm_navigator_ms?: number; batch_ms?: number; settle_ms?: number; turn_ms?: number }
  | { type: 'CONNECTED' }
  | { type: 'DISCONNECTED' }
  | { type: 'CLOSED' }
  | { type: 'ERROR'; message: string }

function mergeProgress(run: RunDetails, progress?: RunProgress): RunDetails {
  if (!progress) return run
  return {
    ...run,
    progress: { ...run.progress, ...progress },
    current_atomic_step: progress.current_atomic_step ?? run.current_atomic_step,
  }
}

function reducer(state: StreamState, action: Action): StreamState {
  switch (action.type) {
    case 'CONNECTED':
      return { ...state, connected: true, error: null }
    case 'DISCONNECTED':
      return { ...state, connected: false }
    case 'CLOSED':
      return { ...state, closed: true, connected: false }
    case 'ERROR':
      return {
        ...state,
        error: action.message,
        run: state.run ? { ...state.run, status: 'error' as RunDetails['status'] } : state.run,
      }
    case 'SNAPSHOT':
      return {
        ...state,
        run: action.run,
        reportReady: false,
        reportPath: null,
      }
    case 'STEP_START': {
      if (!state.run) return state
      const exists = state.run.steps.some((s) => s.index === action.step.index)
      const steps = exists
        ? state.run.steps.map((s) => (s.index === action.step.index ? action.step : s))
        : [...state.run.steps, action.step]
      return { ...state, run: { ...state.run, steps } }
    }
    case 'STEP_END': {
      if (!state.run) return state
      const steps = state.run.steps.map((s) =>
        s.index === action.step.index ? action.step : s,
      )
      return {
        ...state,
        run: { ...state.run, steps, step_count: steps.length },
      }
    }
    case 'PLAN_UPDATE':
      if (!state.run) return state
      return { ...state, run: { ...state.run, plan: action.plan } }
    case 'STEPS_EXTRACTED':
      if (!state.run) return state
      return {
        ...state,
        run: { ...state.run, extracted_steps: action.steps },
      }
    case 'MILESTONES_UPDATED':
      if (!state.run) return state
      return {
        ...state,
        run: mergeProgress(
          { ...state.run, extracted_steps: action.steps },
          action.progress,
        ),
      }
    case 'ATOMIC_STEP_FOCUS':
      if (!state.run) return state
      return {
        ...state,
        run: {
          ...state.run,
          current_atomic_step: action.step,
          progress: {
            ...state.run.progress,
            current_atomic_step: action.step,
            atomic_progress: {
              ...state.run.progress?.atomic_progress,
              current: action.step,
              total: action.total,
            },
          },
        },
      }
    case 'ATOMIC_STEP_DONE': {
      if (!state.run) return state
      const progressCurrent = action.progress?.current_atomic_step
      const progressCompleted = action.progress?.atomic_progress?.completed
      const next =
        progressCurrent ??
        state.run.extracted_steps?.find((s) => s.step > action.step)?.step ??
        null
      return {
        ...state,
        run: mergeProgress(
          {
            ...state.run,
            current_atomic_step: next,
            progress: action.progress
              ? {
                  ...state.run.progress,
                  ...action.progress,
                  atomic_progress: {
                    ...state.run.progress?.atomic_progress,
                    ...action.progress.atomic_progress,
                    completed:
                      action.progress.atomic_progress?.completed ??
                      progressCompleted ??
                      state.run.progress?.atomic_progress?.completed,
                  },
                }
              : state.run.progress,
          },
          action.progress,
        ),
      }
    }
    case 'VALIDATION_BLOCKED':
      if (!state.run) return state
      return { ...state, run: mergeProgress(state.run, action.progress) }
    case 'VALIDATION_PASSED':
    case 'ATOMIC_STEP_COMPLETED':
      if (!state.run) return state
      return { ...state, run: mergeProgress(state.run, action.progress) }
    case 'RUN_FINISHED':
      if (!state.run) return state
      return {
        ...state,
        run: {
          ...mergeProgress(state.run, action.progress),
          status: action.status as RunDetails['status'],
          summary: action.summary,
        },
      }
    case 'REPORT_READY':
      return {
        ...state,
        reportReady: true,
        reportPath: action.reportPath,
      }
    case 'TOOL_WRITTEN':
      if (!state.run) return state
      return {
        ...state,
        run: { ...state.run, new_tools: [...state.run.new_tools, action.name] },
      }
    case 'DONE':
      if (!state.run) return state
      return {
        ...state,
        run: {
          ...state.run,
          status: action.status as RunDetails['status'],
          summary: action.summary,
        },
      }
    case 'STATUS':
      if (!state.run) return state
      return {
        ...state,
        run: { ...state.run, status: action.status as RunDetails['status'] },
      }
    case 'TOKENS_UPDATE':
      if (!state.run) return state
      return {
        ...state,
        run: {
          ...state.run,
          tokens: action.tokens,
          prompt_tokens: action.prompt_tokens,
          completion_tokens: action.completion_tokens,
          cache_tokens: action.cache_tokens,
          cost_usd: action.cost_usd,
        },
      }
    case 'TURN_TIMING':
      if (!state.run) return state
      return {
        ...state,
        run: {
          ...state.run,
          turn_timing: {
            snapshot_ms: action.snapshot_ms,
            llm_navigator_ms: action.llm_navigator_ms,
            batch_ms: action.batch_ms,
            settle_ms: action.settle_ms,
            turn_ms: action.turn_ms,
          },
        },
      }
    default:
      return state
  }
}

export function useRunStream(runId: string | null) {
  const [state, dispatch] = useReducer(reducer, {
    run: null,
    connected: false,
    closed: false,
    error: null,
    reportReady: false,
    reportPath: null,
  })
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!runId) return

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = window.location.host
    const ws = new WebSocket(`${proto}://${host}/ws/runs/${runId}`)
    wsRef.current = ws

    ws.onopen = () => dispatch({ type: 'CONNECTED' })

    ws.onmessage = (e) => {
      let event: WSEvent
      try {
        event = JSON.parse(e.data) as WSEvent
      } catch {
        return
      }
      switch (event.type) {
        case 'snapshot':
          dispatch({ type: 'SNAPSHOT', run: event.run })
          break
        case 'step_start':
          dispatch({ type: 'STEP_START', step: event.step })
          break
        case 'step_end':
          dispatch({ type: 'STEP_END', step: event.step })
          break
        case 'plan_update':
          dispatch({ type: 'PLAN_UPDATE', plan: event.plan })
          break
        case 'steps_extracted':
          dispatch({ type: 'STEPS_EXTRACTED', steps: event.steps })
          break
        case 'milestones_updated':
          dispatch({
            type: 'MILESTONES_UPDATED',
            steps: event.milestones,
            progress: event.progress,
          })
          break
        case 'atomic_step_focus':
          dispatch({
            type: 'ATOMIC_STEP_FOCUS',
            step: event.step,
            total: event.total,
            atomic: event.atomic,
          })
          break
        case 'atomic_step_done':
          dispatch({ type: 'ATOMIC_STEP_DONE', step: event.step, progress: event.progress })
          break
        case 'validation_blocked':
          dispatch({
            type: 'VALIDATION_BLOCKED',
            atomicStep: event.atomic_step,
            message: event.message,
            progress: event.progress,
          })
          break
        case 'validation_passed':
          dispatch({
            type: 'VALIDATION_PASSED',
            atomicStep: event.atomic_step,
            message: event.message,
            progress: event.progress,
          })
          break
        case 'atomic_step_completed':
          dispatch({
            type: 'ATOMIC_STEP_COMPLETED',
            atomicStep: event.atomic_step,
            message: event.message,
            progress: event.progress,
          })
          break
        case 'run_finished':
          dispatch({
            type: 'RUN_FINISHED',
            status: event.status,
            summary: event.summary,
            progress: event.progress,
          })
          break
        case 'report_ready':
          dispatch({ type: 'REPORT_READY', reportPath: event.report_path })
          break
        case 'tool_written':
          dispatch({ type: 'TOOL_WRITTEN', name: event.name })
          break
        case 'done':
          dispatch({ type: 'DONE', status: event.status, summary: event.summary })
          break
        case 'status':
          dispatch({ type: 'STATUS', status: event.status })
          break
        case 'tokens_update':
          dispatch({
            type: 'TOKENS_UPDATE',
            tokens: event.tokens,
            prompt_tokens: event.prompt_tokens,
            completion_tokens: event.completion_tokens,
            cache_tokens: event.cache_tokens,
            cost_usd: event.cost_usd,
          })
          break
        case 'turn_timing':
          dispatch({
            type: 'TURN_TIMING',
            snapshot_ms: event.snapshot_ms,
            llm_navigator_ms: event.llm_navigator_ms,
            batch_ms: event.batch_ms,
            settle_ms: event.settle_ms,
            turn_ms: event.turn_ms,
          })
          break
        case 'error':
          dispatch({ type: 'ERROR', message: event.message })
          break
        case 'closed':
          dispatch({ type: 'CLOSED' })
          break
        default:
          break
      }
    }

    ws.onerror = () => dispatch({ type: 'ERROR', message: 'WebSocket error' })
    ws.onclose = () => dispatch({ type: 'DISCONNECTED' })

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [runId])

  return state
}
