import { Download, Loader2, MoreHorizontal, Pencil, Play, RefreshCw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { executionModeChipClass } from '@/lib/run-status'
import type { ProjectTask } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  task: ProjectTask
  running: boolean
  disabled: boolean
  disabledHint?: string
  deleting?: boolean
  includedInSuite?: boolean
  onIncludedInSuiteChange?: (included: boolean) => void
  onRun: () => void
  onRetrain?: () => void
  onExport?: () => void
  onEdit: () => void
  onDelete: () => void
}

export default function TestRow({
  task,
  running,
  disabled,
  disabledHint,
  deleting = false,
  includedInSuite = true,
  onIncludedInSuiteChange,
  onRun,
  onRetrain,
  onExport,
  onEdit,
  onDelete,
}: Props) {
  const excluded = onIncludedInSuiteChange != null && !includedInSuite
  const displayName = task.name || 'Untitled test'

  return (
    <div
      className={cn(
        'group grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-xl px-2 py-3.5 sm:px-3',
        'transition-colors duration-150 hover:bg-accent/40 focus-within:bg-accent/40',
      )}
      role="listitem"
    >
      <div className="flex min-w-0 items-start gap-3">
        {onIncludedInSuiteChange && (
          <div
            className="pt-0.5 shrink-0"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <Checkbox
              checked={includedInSuite}
              disabled={disabled}
              onCheckedChange={(checked) => onIncludedInSuiteChange(checked === true)}
              aria-label={
                includedInSuite
                  ? `Include ${displayName} in Run All`
                  : `Exclude ${displayName} from Run All`
              }
            />
          </div>
        )}

        <div
          className={cn(
            'min-w-0 flex-1 space-y-1',
            excluded && 'text-muted-foreground/70',
          )}
        >
          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            <p className="text-sm font-semibold leading-snug truncate">{displayName}</p>
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
            <p className="text-xs text-muted-foreground/80 line-clamp-1">
              <span className="text-muted-foreground/60">Criteria:</span> {task.success_criteria}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 pt-0.5 text-[11px] text-muted-foreground">
            <span className="mono">{task.max_steps} steps</span>
            {task.headless && (
              <>
                <span aria-hidden className="text-muted-foreground/40">
                  ·
                </span>
                <span>headless</span>
              </>
            )}
            {task.fresh_profile !== false && (
              <>
                <span aria-hidden className="text-muted-foreground/40">
                  ·
                </span>
                <span>fresh profile</span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1 shrink-0 self-end sm:self-start">
        <Button
          size="sm"
          onClick={onRun}
          disabled={disabled || running}
          title={disabled && disabledHint ? disabledHint : undefined}
          aria-label="Run test"
        >
          {running ? (
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
              disabled={deleting}
              aria-label="Test actions"
            >
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {task.has_trained_replay && onRetrain && (
              <>
                <DropdownMenuItem
                  onClick={onRetrain}
                  disabled={disabled || running}
                >
                  <RefreshCw className="h-4 w-4" />
                  Retrain
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuItem onClick={onEdit} disabled={disabled}>
              <Pencil className="h-4 w-4" />
              Edit
            </DropdownMenuItem>
            {onExport && (
              <DropdownMenuItem onClick={onExport} disabled={deleting}>
                <Download className="h-4 w-4" />
                Export
              </DropdownMenuItem>
            )}
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  disabled={disabled || deleting}
                  onSelect={(e) => e.preventDefault()}
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </DropdownMenuItem>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete &quot;{displayName}&quot;?</AlertDialogTitle>
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
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
