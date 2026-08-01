import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { cancelRun } from '@/api'
import { startProjectTaskRun, waitForRunTerminal } from '@/lib/project-run'
import type { Project, ProjectTask } from '@/types'

export type SuiteTaskStatus =
  | 'queued'
  | 'running'
  | 'pass'
  | 'fail'
  | 'error'
  | 'cancelled'
  | 'skipped'

export type SuiteTaskResult = {
  taskId: string
  status: SuiteTaskStatus
  runId?: string
}

export type SuitePhase = 'idle' | 'running' | 'complete' | 'cancelled'

export type SuiteState = {
  phase: SuitePhase
  projectId: string | null
  results: SuiteTaskResult[]
  currentTaskId: string | null
}

const INITIAL: SuiteState = {
  phase: 'idle',
  projectId: null,
  results: [],
  currentTaskId: null,
}

function failedCount(results: SuiteTaskResult[]): number {
  return results.filter(
    (r) => r.status === 'fail' || r.status === 'error' || r.status === 'cancelled',
  ).length
}

function successCount(results: SuiteTaskResult[]): number {
  return results.filter((r) => r.status === 'pass').length
}

export type ProjectSuiteRunner = {
  state: SuiteState
  runAll: (project: Project) => Promise<void>
  stop: () => Promise<void>
  reset: () => void
  resultFor: (taskId: string) => SuiteTaskResult | undefined
  isRunning: boolean
  successCount: number
  failedCount: number
  totalsReady: boolean
}

const SuiteRunnerContext = createContext<ProjectSuiteRunner | null>(null)

export function SuiteRunnerProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<SuiteState>(INITIAL)
  const abortRef = useRef<AbortController | null>(null)
  const currentRunIdRef = useRef<string | null>(null)

  const stop = useCallback(async () => {
    abortRef.current?.abort()
    const runId = currentRunIdRef.current
    if (runId) {
      try {
        await cancelRun(runId)
      } catch {
        // ignore — run may already be terminal
      }
    }
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    currentRunIdRef.current = null
    setState(INITIAL)
  }, [])

  const runAll = useCallback(
    async (project: Project) => {
      if (project.tasks.length === 0) return

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      const results: SuiteTaskResult[] = project.tasks.map((t) => ({
        taskId: t.id,
        status: 'queued' as const,
      }))

      setState({
        phase: 'running',
        projectId: project.id,
        results: [...results],
        currentTaskId: null,
      })

      let stoppedEarly = false

      for (let i = 0; i < project.tasks.length; i++) {
        if (controller.signal.aborted) {
          stoppedEarly = true
          for (let j = i; j < results.length; j++) {
            if (results[j].status === 'queued') {
              results[j] = { ...results[j], status: 'skipped' }
            }
          }
          break
        }

        const task = project.tasks[i]
        results[i] = { taskId: task.id, status: 'running' }
        setState({
          phase: 'running',
          projectId: project.id,
          results: [...results],
          currentTaskId: task.id,
        })

        try {
          const started = await startProjectTaskRun(project, task)
          currentRunIdRef.current = started.run_id
          results[i] = { ...results[i], runId: started.run_id }
          setState({
            phase: 'running',
            projectId: project.id,
            results: [...results],
            currentTaskId: task.id,
          })
          await queryClient.invalidateQueries({ queryKey: ['runs'] })

          const finished = await waitForRunTerminal(started.run_id, {
            signal: controller.signal,
          })
          const status: SuiteTaskStatus =
            finished.status === 'pass'
              ? 'pass'
              : finished.status === 'cancelled'
                ? 'cancelled'
                : finished.status === 'error'
                  ? 'error'
                  : 'fail'
          results[i] = { taskId: task.id, status, runId: started.run_id }
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') {
            stoppedEarly = true
            if (results[i].status === 'running') {
              results[i] = {
                ...results[i],
                status: 'cancelled',
              }
            }
            for (let j = i + 1; j < results.length; j++) {
              if (results[j].status === 'queued') {
                results[j] = { ...results[j], status: 'skipped' }
              }
            }
            break
          }
          results[i] = {
            ...results[i],
            status: 'error',
          }
        } finally {
          currentRunIdRef.current = null
        }

        setState({
          phase: 'running',
          projectId: project.id,
          results: [...results],
          currentTaskId: task.id,
        })
      }

      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })

      setState({
        phase: stoppedEarly ? 'cancelled' : 'complete',
        projectId: project.id,
        results: [...results],
        currentTaskId: null,
      })
    },
    [queryClient],
  )

  const resultFor = useCallback(
    (taskId: string): SuiteTaskResult | undefined =>
      state.results.find((r) => r.taskId === taskId),
    [state.results],
  )

  const value = useMemo<ProjectSuiteRunner>(
    () => ({
      state,
      runAll,
      stop,
      reset,
      resultFor,
      isRunning: state.phase === 'running',
      successCount: successCount(state.results),
      failedCount: failedCount(state.results),
      totalsReady: state.phase === 'complete' || state.phase === 'cancelled',
    }),
    [state, runAll, stop, reset, resultFor],
  )

  return <SuiteRunnerContext.Provider value={value}>{children}</SuiteRunnerContext.Provider>
}

export function useProjectSuiteRunner(): ProjectSuiteRunner {
  const ctx = useContext(SuiteRunnerContext)
  if (!ctx) {
    throw new Error('useProjectSuiteRunner must be used within SuiteRunnerProvider')
  }
  return ctx
}

export function taskDisplayName(task: ProjectTask): string {
  return task.name?.trim() || 'Untitled test'
}

export function suiteStatusLabel(status: SuiteTaskResult['status']): string {
  switch (status) {
    case 'queued':
      return 'Queued'
    case 'running':
      return 'Running'
    case 'pass':
      return 'Passed'
    case 'fail':
      return 'Failed'
    case 'error':
      return 'Error'
    case 'cancelled':
      return 'Cancelled'
    case 'skipped':
      return 'Skipped'
    default:
      return status
  }
}

export function isTerminalSuiteStatus(status: SuiteTaskStatus): boolean {
  return status !== 'queued' && status !== 'running'
}
