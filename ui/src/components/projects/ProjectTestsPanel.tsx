import { FlaskConical, Loader2, Play, Plus, RefreshCw } from 'lucide-react'
import TestRow from '@/components/projects/TestRow'
import { Button } from '@/components/ui/button'
import type { ProjectSuiteRunner } from '@/hooks/useProjectSuiteRunner'
import type { Project, ProjectTask } from '@/types'

interface Props {
  project: Project
  suite: ProjectSuiteRunner
  suiteBusy: boolean
  excludedTaskIds: Set<string>
  runningId: string | null
  anySuiteRunning: boolean
  runActionsBlocked: boolean
  runGateHint?: string
  isRemovingTask: boolean
  allIncluded: boolean
  includedCount: number
  noneIncluded: boolean
  includedTrainedCount: number
  allTrainedIncluded: boolean
  noneTrainedIncluded: boolean
  trainedCount: number
  onRunAll: () => void
  onRetrainAll: () => void
  onAddTest: () => void
  onSetTaskIncluded: (taskId: string, included: boolean) => void
  onSelectAll: () => void
  onSelectNone: () => void
  onRunTask: (project: Project, task: ProjectTask) => void
  onRetrainTask: (project: Project, task: ProjectTask) => void
  onEditTask: (task: ProjectTask) => void
  onDeleteTask: (taskId: string) => void
}

export default function ProjectTestsPanel({
  project,
  suite,
  suiteBusy,
  excludedTaskIds,
  runningId,
  anySuiteRunning,
  runActionsBlocked,
  runGateHint,
  isRemovingTask,
  allIncluded,
  includedCount,
  noneIncluded,
  includedTrainedCount,
  allTrainedIncluded,
  noneTrainedIncluded,
  trainedCount,
  onRunAll,
  onRetrainAll,
  onAddTest,
  onSetTaskIncluded,
  onSelectAll,
  onSelectNone,
  onRunTask,
  onRetrainTask,
  onEditTask,
  onDeleteTask,
}: Props) {
  if (project.tasks.length === 0) {
    return (
      <div className="py-16 text-center space-y-4 animate-in fade-in-0 duration-300">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <FlaskConical className="h-6 w-6" aria-hidden />
        </div>
        <div className="space-y-1.5">
          <h2 className="text-base font-medium">No tests yet</h2>
          <p className="text-sm text-muted-foreground max-w-sm mx-auto">
            Add a test here or save a run to this project from New Run.
          </p>
        </div>
        <Button size="sm" onClick={onAddTest} className="rounded-full">
          <Plus className="h-4 w-4" />
          Add test
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-3 animate-in fade-in-0 duration-300">
      <div className="rounded-xl border border-border/80 bg-card/40 px-3 py-2.5 sm:px-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground/80">{includedCount}</span> of{' '}
            {project.tasks.length} selected
            {trainedCount > 0 && (
              <span className="text-muted-foreground/80">
                {' '}
                · {includedTrainedCount} trained
              </span>
            )}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              className="h-8 rounded-full"
              disabled={
                suiteBusy || noneIncluded || anySuiteRunning || runningId !== null || runActionsBlocked
              }
              title={runGateHint}
              onClick={onRunAll}
            >
              {suiteBusy && suite.state.mode === 'run' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {allIncluded ? 'Run All' : `Run ${includedCount}`}
            </Button>
            {trainedCount > 0 && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 rounded-full"
                disabled={
                  suiteBusy ||
                  noneTrainedIncluded ||
                  anySuiteRunning ||
                  runningId !== null ||
                  runActionsBlocked
                }
                title={
                  noneTrainedIncluded ? 'Select trained tests to retrain' : runGateHint
                }
                onClick={onRetrainAll}
              >
                {suiteBusy && suite.state.mode === 'retrain' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {allTrainedIncluded ? 'Retrain All' : `Retrain ${includedTrainedCount}`}
              </Button>
            )}
            <div className="hidden sm:block h-4 w-px bg-border/60" aria-hidden />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-xs"
              disabled={suiteBusy || allIncluded}
              onClick={onSelectAll}
            >
              Select all
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-xs"
              disabled={suiteBusy || noneIncluded}
              onClick={onSelectNone}
            >
              Select none
            </Button>
          </div>
        </div>
      </div>

      <div className="space-y-0.5" role="list" aria-label={`Tests in ${project.name}`}>
        {project.tasks.map((task, index) => (
          <div
            key={task.id}
            className="animate-in fade-in-0 slide-in-from-bottom-1 duration-300"
            style={{ animationDelay: `${Math.min(index, 10) * 30}ms` }}
          >
            <TestRow
              task={task}
              running={runningId === task.id}
              disabled={
                anySuiteRunning ||
                (runningId !== null && runningId !== task.id) ||
                runActionsBlocked
              }
              disabledHint={runGateHint}
              deleting={isRemovingTask}
              includedInSuite={!excludedTaskIds.has(task.id)}
              onIncludedInSuiteChange={(included) => onSetTaskIncluded(task.id, included)}
              onRun={() => onRunTask(project, task)}
              onRetrain={() => onRetrainTask(project, task)}
              onEdit={() => onEditTask(task)}
              onDelete={() => onDeleteTask(task.id)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
