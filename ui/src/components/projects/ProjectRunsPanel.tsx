import { Link } from 'react-router-dom'
import { BarChart3 } from 'lucide-react'
import TestResultRow from '@/components/projects/TestResultRow'
import {
  formatResultsSummary,
  latestRunsByProjectTaskId,
  projectTestResultsSummary,
  resolveTestRowStatus,
  runsForProjectTask,
} from '@/lib/project-task-status'
import type { Project, RunSummary } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  project: Project
  runs: RunSummary[]
}

export default function ProjectRunsPanel({ project, runs }: Props) {
  const latestByTask = latestRunsByProjectTaskId(runs, project.id)
  const summary = projectTestResultsSummary(project.tasks, latestByTask)
  const summaryText = formatResultsSummary(summary)
  const hasAnyRuns = project.tasks.some((t) => latestByTask.has(t.id))

  if (project.tasks.length === 0) {
    return (
      <div className="py-14 text-center space-y-4 animate-in fade-in-0 duration-300">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <BarChart3 className="h-6 w-6" aria-hidden />
        </div>
        <div className="space-y-1.5">
          <h2 className="text-base font-medium">No tests to show results for</h2>
          <p className="text-sm text-muted-foreground max-w-sm mx-auto">
            Add tests on the Tests tab, then run them to see outcomes here.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4 animate-in fade-in-0 duration-300">
      <div
        className={cn(
          'rounded-xl border border-border/80 bg-card/40 px-3 py-2.5 sm:px-4',
          summary.failed > 0 && 'border-destructive/25 bg-destructive/[0.03]',
        )}
      >
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground/90">Latest results</span>
          <span aria-hidden> · </span>
          {summaryText}
        </p>
      </div>

      <div className="space-y-0.5" role="list" aria-label={`Test results for ${project.name}`}>
        {project.tasks.map((task) => {
          const latestRun = latestByTask.get(task.id)
          const status = resolveTestRowStatus({ latestRun, suiteActive: false })
          const attemptRuns = runsForProjectTask(runs, project.id, task.id, 3)

          return (
            <div key={task.id} role="listitem">
              <TestResultRow task={task} status={status} attemptRuns={attemptRuns} />
            </div>
          )
        })}
      </div>

      {hasAnyRuns && (
        <p className="text-center pt-2">
          <Link
            to="/"
            className="text-xs text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
          >
            View full run history →
          </Link>
        </p>
      )}
    </div>
  )
}
