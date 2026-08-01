import { Link } from 'react-router-dom'
import { Loader2, Pencil, Play, Trash2 } from 'lucide-react'
import { SuiteStatusIcon } from '@/components/projects/SuiteProgressPanel'
import { Button } from '@/components/ui/button'
import { CardDescription } from '@/components/ui/card'
import type { SuiteTaskResult } from '@/hooks/useProjectSuiteRunner'
import { suiteStatusLabel } from '@/hooks/useProjectSuiteRunner'
import { executionModeChipClass } from '@/lib/run-status'
import type { ProjectTask } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  task: ProjectTask
  suiteResult?: SuiteTaskResult
  running: boolean
  disabled: boolean
  onRun: () => void
  onEdit: () => void
  onDelete: () => void
}

export default function TestRow({
  task,
  suiteResult,
  running,
  disabled,
  onRun,
  onEdit,
  onDelete,
}: Props) {
  return (
    <li
      className={cn(
        'flex items-start gap-3 px-4 py-3 group hover:bg-accent/20 transition-colors',
        suiteResult?.status === 'running' && 'bg-primary/5',
      )}
    >
      {suiteResult && (
        <div className="pt-0.5 shrink-0" title={suiteStatusLabel(suiteResult.status)}>
          <SuiteStatusIcon status={suiteResult.status} size="sm" />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          <p className="text-sm font-medium leading-snug line-clamp-1 truncate">
            {task.name || 'Untitled test'}
          </p>
          {task.has_trained_replay && (
            <span
              title="Successful training saved"
              className={cn(
                'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-medium',
                executionModeChipClass(true),
              )}
            >
              Trained
            </span>
          )}
          {suiteResult?.runId && (
            <Link
              to={`/runs/${suiteResult.runId}`}
              className="text-[10px] font-medium text-primary hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              Open
            </Link>
          )}
        </div>
        <p className="text-sm leading-snug line-clamp-2 text-muted-foreground mt-0.5">{task.task}</p>
        {task.success_criteria && (
          <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
            Criteria: {task.success_criteria}
          </p>
        )}
        <CardDescription className="flex gap-3 mt-1 text-[10px]">
          <span className="mono">{task.max_steps} steps</span>
          {task.headless && <span>headless</span>}
        </CardDescription>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Button size="sm" onClick={onRun} disabled={disabled || running}>
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          Run
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-muted-foreground"
          onClick={onEdit}
          disabled={disabled}
          title="Edit test"
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
          onClick={onDelete}
          disabled={disabled}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </li>
  )
}
