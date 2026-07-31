import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Globe, History, MoreHorizontal, RotateCcw, Trash2 } from 'lucide-react'
import { deleteRun } from '@/api'
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
} from '@/components/ui/alert-dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useRunModal } from '@/contexts/RunModalContext'
import { runSummaryToDraft } from '@/lib/run-draft'
import {
  buildRunThreads,
  sortThreadsForSidebar,
  testGroupShouldExpand,
  testHasActiveRun,
  testRunLabel,
  threadHasActiveRun,
  threadIsGrouped,
  threadRunLabel,
  threadShouldExpand,
  threadTitle,
  type RunTestGroup,
  type RunThread,
} from '@/lib/run-threads'
import {
  elapsedSeconds,
  executionModeChipClass,
  executionModeShortLabel,
  formatElapsed,
  statusLabel,
} from '@/lib/run-status'
import { cn } from '@/lib/utils'
import type { Project, RunStatus, RunSummary } from '@/types'

interface Props {
  runs: RunSummary[]
  activeRunId?: string | null
  variant?: 'sidebar' | 'home'
  limit?: number
  emptyMessage?: string
  projectNames?: Record<string, string>
  projects?: Project[]
}

function StatusDot({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, string> = {
    pending: 'bg-warning animate-pulse',
    running: 'bg-brand-blue animate-pulse-slow',
    awaiting_human: 'bg-warning animate-pulse',
    pass: 'bg-success',
    fail: 'bg-destructive',
    error: 'bg-destructive',
    cancelled: 'bg-muted-foreground',
  }
  return (
    <span
      className={cn('inline-block w-2 h-2 rounded-full flex-shrink-0', map[status] ?? 'bg-muted')}
    />
  )
}

function ModeChip({ useReplayScript, compact = false }: { useReplayScript?: boolean; compact?: boolean }) {
  return (
    <span
      title={useReplayScript ? 'Automatic execution' : 'Training'}
      className={cn(
        'inline-flex items-center rounded border font-semibold uppercase tracking-wide flex-shrink-0',
        compact ? 'px-1 py-0 text-[9px]' : 'px-1.5 py-0.5 text-[10px]',
        executionModeChipClass(useReplayScript),
      )}
    >
      {executionModeShortLabel(useReplayScript)}
    </span>
  )
}

function MetaSep() {
  return <span className="text-muted-foreground/50 shrink-0">·</span>
}

interface RunActionsProps {
  run: RunSummary
  projects?: Project[]
  onDelete: (run: RunSummary) => void
}

function RunActions({ run, projects, onDelete }: RunActionsProps) {
  const { openNewRun } = useRunModal()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
          }}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuItem
          onClick={(e) => {
            e.stopPropagation()
            openNewRun(runSummaryToDraft(run, projects))
          }}
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Re-run
        </DropdownMenuItem>
        <DropdownMenuItem
          className="text-destructive focus:text-destructive"
          onClick={(e) => {
            e.stopPropagation()
            onDelete(run)
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

interface RunRowProps {
  run: RunSummary
  active: boolean
  indented?: boolean
  label?: string
  roomy?: boolean
  projects?: Project[]
  onDelete: (run: RunSummary) => void
}

function RunRow({ run, active, indented = false, label, roomy = false, projects, onDelete }: RunRowProps) {
  const title = label ?? (run.name || run.task)
  const showModeChip = !label

  return (
    <div
      className={cn(
        'group relative rounded-md transition-colors border-l-2',
        active ? 'bg-accent/40 border-primary' : 'border-transparent hover:bg-accent/30',
        indented && 'ml-3',
      )}
    >
      <Link
        to={`/runs/${run.run_id}`}
        title={`${title} · ${run.step_count} steps`}
        className={cn('block w-full text-left pr-9', roomy ? 'px-3 py-2.5' : 'px-3 py-2')}
      >
        <p
          className={cn(
            'truncate leading-snug mb-1',
            indented ? 'text-xs font-medium' : 'text-sm font-medium',
            active ? 'text-foreground' : 'text-foreground/90',
          )}
        >
          {title}
        </p>
        <div className="flex items-center gap-1.5 min-w-0 text-[11px] text-muted-foreground">
          <StatusDot status={run.status} />
          <span className="truncate">{statusLabel(run.status)}</span>
          {showModeChip && (
            <>
              <MetaSep />
              <ModeChip useReplayScript={run.use_replay_script} compact />
            </>
          )}
          <MetaSep />
          <span className="mono truncate">
            {formatElapsed(elapsedSeconds(run.started_at, run.finished_at))}
          </span>
        </div>
      </Link>
      <div className="absolute right-0.5 top-1/2 -translate-y-1/2">
        <RunActions run={run} projects={projects} onDelete={onDelete} />
      </div>
    </div>
  )
}

function CollapsePanel({ expanded, children }: { expanded: boolean; children: ReactNode }) {
  return (
    <div
      className={cn(
        'grid transition-[grid-template-rows,opacity] duration-200 ease-out',
        expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
      )}
    >
      <div className="overflow-hidden">{children}</div>
    </div>
  )
}

function LivePulse() {
  return (
    <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand-blue animate-pulse-slow flex-shrink-0" />
  )
}

interface ProjectHeaderProps {
  title: string
  expanded: boolean
  onToggle: () => void
  hasActiveRun: boolean
}

function ProjectHeader({ title, expanded, onToggle, hasActiveRun }: ProjectHeaderProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center gap-1.5 min-w-0 px-2 py-1.5 text-left transition-colors hover:text-foreground/90"
      title={expanded ? 'Collapse project' : 'Expand project'}
    >
      {expanded ? (
        <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground/70" />
      ) : (
        <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/70" />
      )}
      <Globe className="h-3 w-3 shrink-0 text-muted-foreground/60" />
      <span className="truncate flex-1 text-[11px] font-semibold tracking-wide text-muted-foreground">
        {title}
      </span>
      {hasActiveRun && <LivePulse />}
    </button>
  )
}

interface TestHeaderProps {
  title: string
  expanded: boolean
  onToggle: () => void
  hasActiveRun: boolean
  indent?: boolean
}

function TestHeader({
  title,
  expanded,
  onToggle,
  hasActiveRun,
  indent = false,
}: TestHeaderProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        'w-full flex items-center gap-1.5 min-w-0 px-2 py-1.5 text-left transition-colors hover:text-foreground',
        indent && 'ml-3',
      )}
      title={expanded ? 'Collapse test' : 'Expand test'}
    >
      {expanded ? (
        <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground/70" />
      ) : (
        <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/70" />
      )}
      <span className="truncate flex-1 text-xs font-medium text-foreground/75 text-left">{title}</span>
      {hasActiveRun && <LivePulse />}
    </button>
  )
}

interface TestGroupBlockProps {
  test: RunTestGroup
  activeRunId: string | null
  expanded: boolean
  onToggle: () => void
  onDelete: (run: RunSummary) => void
  roomy?: boolean
  projects?: Project[]
}

function TestGroupBlock({
  test,
  activeRunId,
  expanded,
  onToggle,
  onDelete,
  roomy = false,
  projects,
}: TestGroupBlockProps) {
  return (
    <div className="space-y-px">
      <TestHeader
        title={test.title}
        expanded={expanded}
        onToggle={onToggle}
        hasActiveRun={testHasActiveRun(test)}
        indent
      />
      <CollapsePanel expanded={expanded}>
        <div className="space-y-px border-l border-border/50 ml-6 pl-1">
          {test.runs.map((run) => (
            <RunRow
              key={run.run_id}
              run={run}
              active={activeRunId === run.run_id}
              indented
              label={testRunLabel(run, test)}
              roomy={roomy}
              projects={projects}
              onDelete={onDelete}
            />
          ))}
        </div>
      </CollapsePanel>
    </div>
  )
}

interface ProjectThreadBlockProps {
  thread: RunThread
  activeRunId: string | null
  expanded: boolean
  onToggle: () => void
  expandedTests: Set<string>
  onToggleTest: (testId: string) => void
  onDelete: (run: RunSummary) => void
  projectNames: Record<string, string>
  roomy?: boolean
  projects?: Project[]
}

function ProjectThreadBlock({
  thread,
  activeRunId,
  expanded,
  onToggle,
  expandedTests,
  onToggleTest,
  onDelete,
  projectNames,
  roomy = false,
  projects,
}: ProjectThreadBlockProps) {
  const testGroups = thread.testGroups ?? []

  return (
    <div className="space-y-px">
      <ProjectHeader
        title={threadTitle(thread, projectNames)}
        expanded={expanded}
        onToggle={onToggle}
        hasActiveRun={threadHasActiveRun(thread)}
      />
      <CollapsePanel expanded={expanded}>
        <div className="space-y-px border-l border-border/50 ml-3 pl-1">
          {testGroups.map((test) => (
            <TestGroupBlock
              key={test.id}
              test={test}
              activeRunId={activeRunId}
              expanded={expandedTests.has(test.id)}
              onToggle={() => onToggleTest(test.id)}
              onDelete={onDelete}
              roomy={roomy}
              projects={projects}
            />
          ))}
        </div>
      </CollapsePanel>
    </div>
  )
}

interface ChainThreadBlockProps {
  thread: RunThread
  activeRunId: string | null
  expanded: boolean
  onToggle: () => void
  onDelete: (run: RunSummary) => void
  projectNames: Record<string, string>
  roomy?: boolean
  projects?: Project[]
}

function ChainThreadBlock({
  thread,
  activeRunId,
  expanded,
  onToggle,
  onDelete,
  projectNames,
  roomy = false,
  projects,
}: ChainThreadBlockProps) {
  return (
    <div className="space-y-px">
      <TestHeader
        title={threadTitle(thread, projectNames)}
        expanded={expanded}
        onToggle={onToggle}
        hasActiveRun={threadHasActiveRun(thread)}
      />
      <CollapsePanel expanded={expanded}>
        <div className="space-y-px border-l border-border/50 ml-3 pl-1">
          {thread.runs.map((run) => (
            <RunRow
              key={run.run_id}
              run={run}
              active={activeRunId === run.run_id}
              indented
              label={threadRunLabel(run, thread)}
              roomy={roomy}
              projects={projects}
              onDelete={onDelete}
            />
          ))}
        </div>
      </CollapsePanel>
    </div>
  )
}

export default function RunThreadList({
  runs,
  activeRunId = null,
  variant = 'sidebar',
  limit,
  emptyMessage = 'No runs yet',
  projectNames = {},
  projects = [],
}: Props) {
  const threads = useMemo(() => buildRunThreads(runs), [runs])
  const visibleThreads = useMemo(() => {
    const sorted = sortThreadsForSidebar(threads)
    return limit ? sorted.slice(0, limit) : sorted
  }, [threads, limit])
  const { openNewRun } = useRunModal()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [expandedRoots, setExpandedRoots] = useState<Set<string>>(() => new Set())
  const [deleteTarget, setDeleteTarget] = useState<RunSummary | null>(null)
  const [deleting, setDeleting] = useState(false)
  const roomy = variant === 'home'

  useEffect(() => {
    setExpandedRoots((prev) => {
      const next = new Set(prev)
      for (const thread of threads) {
        if (threadShouldExpand(thread, activeRunId)) {
          next.add(thread.id)
        }
        for (const test of thread.testGroups ?? []) {
          if (testGroupShouldExpand(test, activeRunId)) {
            next.add(thread.id)
            next.add(test.id)
          }
        }
      }
      return next
    })
  }, [threads, activeRunId])

  function toggleExpanded(rootId: string) {
    setExpandedRoots((prev) => {
      const next = new Set(prev)
      if (next.has(rootId)) next.delete(rootId)
      else next.add(rootId)
      return next
    })
  }

  async function handleConfirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteRun(deleteTarget.run_id)
      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      if (location.pathname === `/runs/${deleteTarget.run_id}`) {
        navigate('/')
      }
      setDeleteTarget(null)
    } catch {
      // ignore
    } finally {
      setDeleting(false)
    }
  }

  if (visibleThreads.length === 0) {
    if (variant === 'sidebar') {
      return (
        <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
          <History className="h-8 w-8 text-muted-foreground/50 mb-3" />
          <p className="text-sm font-medium mb-1">No runs yet</p>
          <p className="text-xs text-muted-foreground mb-4">Start your first automation</p>
          <Button variant="ghost" size="sm" onClick={() => openNewRun()}>
            New Run
          </Button>
        </div>
      )
    }
    return <p className="text-xs text-muted-foreground text-center px-4 pt-6">{emptyMessage}</p>
  }

  return (
    <>
      <div className={variant === 'sidebar' ? 'space-y-px' : 'space-y-1'}>
        {visibleThreads.map((thread) => {
          const expanded = expandedRoots.has(thread.id)

          if (!threadIsGrouped(thread)) {
            const run = thread.runs[0]
            return (
              <RunRow
                key={thread.id}
                run={run}
                active={activeRunId === run.run_id}
                roomy={roomy}
                projects={projects}
                onDelete={setDeleteTarget}
              />
            )
          }

          if (thread.projectId && thread.testGroups) {
            return (
              <ProjectThreadBlock
                key={thread.id}
                thread={thread}
                activeRunId={activeRunId}
                expanded={expanded}
                onToggle={() => toggleExpanded(thread.id)}
                expandedTests={expandedRoots}
                onToggleTest={toggleExpanded}
                onDelete={setDeleteTarget}
                projectNames={projectNames}
                roomy={roomy}
                projects={projects}
              />
            )
          }

          return (
            <ChainThreadBlock
              key={thread.id}
              thread={thread}
              activeRunId={activeRunId}
              expanded={expanded}
              onToggle={() => toggleExpanded(thread.id)}
              onDelete={setDeleteTarget}
              projectNames={projectNames}
              roomy={roomy}
              projects={projects}
            />
          )
        })}
      </div>

      <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this run?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the run and its saved history, replay script, and report. Re-runs
              linked to this run will remain but lose their parent link.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleting}
              onClick={(e) => {
                e.preventDefault()
                void handleConfirmDelete()
              }}
            >
              {deleting ? 'Deleting…' : 'Delete run'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

export { StatusDot, ModeChip }
