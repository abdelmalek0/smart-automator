import { Loader2, Pencil, Play, RefreshCw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { executionModeChipClass } from '@/lib/run-status'
import type { ProjectTask } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  task: ProjectTask
  running: boolean
  disabled: boolean
  deleting?: boolean
  /** When false, this test is excluded from Run All. */
  includedInSuite?: boolean
  onIncludedInSuiteChange?: (included: boolean) => void
  onRun: () => void
  onRetrain?: () => void
  onEdit: () => void
  onDelete: () => void
}

export default function TestRow({
  task,
  running,
  disabled,
  deleting = false,
  includedInSuite = true,
  onIncludedInSuiteChange,
  onRun,
  onRetrain,
  onEdit,
  onDelete,
}: Props) {
  const excluded = onIncludedInSuiteChange != null && !includedInSuite

  return (
    <div
      className={cn(
        'flex flex-col gap-3 sm:flex-row sm:items-start rounded-xl border border-border/80 bg-card/50 px-3.5 py-3',
        'transition-all duration-200 hover:border-primary/30 hover:bg-accent/15',
        excluded && 'opacity-55 border-dashed',
      )}
    >
      <div className="flex items-start gap-3 min-w-0 flex-1">
        {onIncludedInSuiteChange && (
          <label
            className="pt-1 shrink-0 flex items-center"
            title={includedInSuite ? 'Included in Run All' : 'Excluded from Run All'}
            onClick={(e) => e.stopPropagation()}
          >
            <input
              type="checkbox"
              className={cn(
                'h-4 w-4 rounded border-border bg-background text-primary',
                'accent-primary cursor-pointer',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                'disabled:cursor-not-allowed disabled:opacity-50',
              )}
              checked={includedInSuite}
              disabled={disabled}
              onChange={(e) => onIncludedInSuiteChange(e.target.checked)}
              aria-label={
                includedInSuite
                  ? `Include ${task.name || 'Untitled test'} in Run All`
                  : `Exclude ${task.name || 'Untitled test'} from Run All`
              }
            />
          </label>
        )}

        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            <p className="text-sm font-semibold leading-snug truncate">
              {task.name || 'Untitled test'}
            </p>
            {excluded && (
              <span className="inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                Excluded
              </span>
            )}
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
          </div>

          <p className="text-sm leading-snug line-clamp-2 text-muted-foreground">{task.task}</p>

          {task.success_criteria && (
            <p className="text-xs text-muted-foreground/90 line-clamp-2">
              <span className="text-muted-foreground/70">Criteria:</span> {task.success_criteria}
            </p>
          )}

          <div className="flex flex-wrap gap-x-3 gap-y-0.5 pt-0.5 text-[10px] text-muted-foreground">
            <span className="mono">{task.max_steps} steps</span>
            {task.headless && <span>headless</span>}
            {task.fresh_profile !== false && <span>fresh profile</span>}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1 shrink-0 self-end sm:self-start">
        <Button size="sm" onClick={onRun} disabled={disabled || running} aria-label="Run test">
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          Run
        </Button>

        {task.has_trained_replay && onRetrain && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                onClick={onRetrain}
                disabled={disabled || running}
                aria-label="Retrain test"
              >
                {running ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Retrain
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              Start a new training run. On pass, replaces the saved replay.
            </TooltipContent>
          </Tooltip>
        )}

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground"
              onClick={onEdit}
              disabled={disabled}
              aria-label="Edit test"
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Edit test</TooltipContent>
        </Tooltip>

        <AlertDialog>
          <Tooltip>
            <TooltipTrigger asChild>
              <AlertDialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-muted-foreground hover:text-destructive"
                  disabled={disabled || deleting}
                  aria-label="Delete test"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </AlertDialogTrigger>
            </TooltipTrigger>
            <TooltipContent>Delete test</TooltipContent>
          </Tooltip>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete &quot;{task.name || 'Untitled test'}&quot;?</AlertDialogTitle>
              <AlertDialogDescription>
                This removes the test from the project. Trained replay data on past runs is not
                deleted.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={onDelete} disabled={deleting}>
                {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  )
}
