import { Download, FlaskConical, Loader2, MoreHorizontal, Play, Plus, RefreshCw, Upload } from 'lucide-react'
import TestRow from '@/components/projects/TestRow'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { ProjectSuiteRunner } from '@/hooks/useProjectSuiteRunner'
import { downloadProjectTestsPack } from '@/lib/project-tests-pack'
import type { Project, ProjectTask } from '@/types'
import { cn } from '@/lib/utils'

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
  isImportingTests: boolean
  importError?: string | null
  allIncluded: boolean
  includedCount: number
  noneIncluded: boolean
  includedTrainedCount: number
  noneTrainedIncluded: boolean
  onRunAll: () => void
  onRetrainAll: () => void
  onAddTest: () => void
  onImportClick: () => void
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
  isImportingTests,
  importError,
  allIncluded,
  includedCount,
  noneIncluded,
  includedTrainedCount,
  noneTrainedIncluded,
  onRunAll,
  onRetrainAll,
  onAddTest,
  onImportClick,
  onSetTaskIncluded,
  onSelectAll,
  onSelectNone,
  onRunTask,
  onRetrainTask,
  onEditTask,
  onDeleteTask,
}: Props) {
  const selectedTasks = project.tasks.filter((task) => !excludedTaskIds.has(task.id))
  const selectionState = allIncluded ? true : noneIncluded ? false : 'indeterminate'
  const actionsDisabled =
    suiteBusy || anySuiteRunning || runningId !== null || runActionsBlocked

  function toggleSelectAll() {
    if (allIncluded) onSelectNone()
    else onSelectAll()
  }

  const importButton = (
    <Button
      type="button"
      size="sm"
      variant="outline"
      className="rounded-full"
      disabled={isImportingTests || suiteBusy}
      onClick={onImportClick}
    >
      {isImportingTests ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Upload className="h-4 w-4" />
      )}
      Import
    </Button>
  )

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
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button size="sm" onClick={onAddTest} className="rounded-full">
            <Plus className="h-4 w-4" />
            Add test
          </Button>
          {importButton}
        </div>
        {importError && <p className="text-sm text-destructive">{importError}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-0.5 animate-in fade-in-0 duration-300">
      <div
        className={cn(
          'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-2 py-2 sm:px-3',
          'border-b border-border/60',
        )}
      >
        <div className="flex min-w-0 items-center gap-3">
          <Checkbox
            checked={selectionState}
            disabled={actionsDisabled}
            onCheckedChange={toggleSelectAll}
            aria-label={allIncluded ? 'Deselect all tests' : 'Select all tests'}
          />
          <button
            type="button"
            className={cn(
              'min-w-0 text-left text-xs text-muted-foreground',
              'hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm',
              actionsDisabled && 'pointer-events-none opacity-50',
            )}
            onClick={toggleSelectAll}
            disabled={actionsDisabled}
          >
            <span className="font-medium text-foreground/80">{includedCount}</span> of{' '}
            {project.tasks.length} selected
          </button>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {includedTrainedCount > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={
                actionsDisabled || noneTrainedIncluded
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
              Retrain
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            disabled={actionsDisabled || noneIncluded}
            title={runGateHint}
            onClick={onRunAll}
          >
            {suiteBusy && suite.state.mode === 'run' ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            Run
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-muted-foreground"
                disabled={actionsDisabled || noneIncluded}
                aria-label="More test actions"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                disabled={noneIncluded}
                onClick={() => downloadProjectTestsPack(project.name, selectedTasks)}
              >
                <Download className="h-4 w-4" />
                Export
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {importError && (
        <p className="px-2 sm:px-3 pt-2 text-sm text-destructive">{importError}</p>
      )}

      <div role="list" aria-label={`Tests in ${project.name}`}>
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
              onExport={() =>
                downloadProjectTestsPack(project.name, [task], { taskName: task.name })
              }
              onEdit={() => onEditTask(task)}
              onDelete={() => onDeleteTask(task.id)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
