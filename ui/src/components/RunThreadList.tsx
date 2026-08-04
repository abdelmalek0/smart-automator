import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Globe,
  History,
  Inbox,
  MoreHorizontal,
  RotateCcw,
  Trash2,
} from 'lucide-react'
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
import { getPrimaryRunAction } from '@/lib/run-draft'
import {
  allThreadExpandIds,
  automaticSourceExistsInTest,
  buildRunThreads,
  collectAutoExpandIds,
  hasAutomaticDependents,
  INITIAL_TEST_RUNS_VISIBLE,
  minimumVisibleSectionRuns,
  nextVisibleTestRunCount,
  sectionAttemptLabel,
  sortThreadsForSidebar,
  TEST_RUNS_PAGE_SIZE,
  testAutomaticRuns,
  testHasActiveRun,
  testTrainingRuns,
  threadHasActiveRun,
  threadTitle,
  type RunModeFilter,
  type RunTestGroup,
  type RunThread,
} from '@/lib/run-threads'
import {
  elapsedSeconds,
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
  modeFilter?: RunModeFilter
  /** When true, show only top-level project/section headers. */
  rootsCollapsed?: boolean
  onRequestExpandRoots?: () => void
  /** Incremented when the Recent section is expanded to open all projects/tests. */
  expandAllToken?: number
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

function MetaSep() {
  return <span className="text-muted-foreground/50 shrink-0">·</span>
}

interface RunRowProps {
  run: RunSummary
  active: boolean
  label: string
  roomy?: boolean
  projects?: Project[]
  onDelete: (run: RunSummary) => void
  /** Extra muted line under the title (e.g. from training id). */
  sourceMeta?: string | null
}

function RunRow({ run, active, label, roomy = false, projects, onDelete, sourceMeta }: RunRowProps) {
  const { openNewRun } = useRunModal()
  const finished = Boolean(run.finished_at) || !['pending', 'running', 'awaiting_human'].includes(run.status)
  const primary = finished ? getPrimaryRunAction(run, projects) : null
  const duration = formatElapsed(elapsedSeconds(run.started_at, run.finished_at))

  return (
    <div
      className={cn(
        'group relative rounded-md transition-colors border-l-2',
        active ? 'bg-accent/40 border-primary' : 'border-transparent hover:bg-accent/30',
      )}
    >
      <Link
        to={`/runs/${run.run_id}`}
        title={`${label} · ${statusLabel(run.status)} · ${duration}`}
        className={cn('block w-full text-left pr-16', roomy ? 'px-3 py-2.5' : 'px-3 py-2')}
      >
        <p
          className={cn(
            'truncate leading-snug mb-0.5 text-sm font-semibold text-foreground',
            active && 'text-foreground',
          )}
        >
          {label}
        </p>
        {sourceMeta ? (
          <p className="mb-1 truncate text-[10px] text-muted-foreground/80">{sourceMeta}</p>
        ) : null}
        <div className="flex items-center gap-1.5 min-w-0 text-[11px] text-muted-foreground">
          <StatusDot status={run.status} />
          <span className="truncate">{statusLabel(run.status)}</span>
          <MetaSep />
          <span className="mono truncate">{duration}</span>
        </div>
      </Link>
      <div className="absolute right-0.5 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
        {primary ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
            title={primary.label}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              openNewRun(primary.draft)
            }}
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
        ) : null}
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
          <DropdownMenuContent align="end" className="w-44">
            {primary ? (
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation()
                  openNewRun(primary.draft)
                }}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {primary.label}
              </DropdownMenuItem>
            ) : null}
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

const CHILD_RAIL = 'ml-3 border-l border-border/50 pl-1.5'

function LivePulse() {
  return (
    <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand-blue animate-pulse-slow flex-shrink-0" />
  )
}

interface ThreadHeaderProps {
  title: string
  level: 'project' | 'group'
  projectIcon?: 'globe' | 'inbox'
  expanded: boolean
  onToggle: () => void
  hasLiveRun: boolean
  containsActive: boolean
  collapseLabel: string
}

function ThreadHeader({
  title,
  level,
  projectIcon,
  expanded,
  onToggle,
  hasLiveRun,
  containsActive,
  collapseLabel,
}: ThreadHeaderProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        'w-full min-w-0 px-2 py-1.5 text-left transition-colors rounded-md hover:bg-accent/30',
        containsActive && !expanded && 'bg-accent/25',
      )}
      title={expanded ? `Collapse ${collapseLabel}` : `Expand ${collapseLabel}`}
    >
      <div className="flex items-center gap-1.5 min-w-0 w-full">
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground/70" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/70" />
        )}
        {level === 'project' && projectIcon === 'globe' ? (
          <Globe className="h-3 w-3 shrink-0 text-muted-foreground/60" />
        ) : null}
        {level === 'project' && projectIcon === 'inbox' ? (
          <Inbox className="h-3 w-3 shrink-0 text-muted-foreground/60" />
        ) : null}
        <span
          className={cn(
            'truncate flex-1 text-left',
            level === 'project'
              ? 'text-[11px] font-semibold uppercase tracking-wide text-muted-foreground'
              : 'text-xs font-medium text-foreground/80',
          )}
        >
          {title}
        </span>
        {!expanded && hasLiveRun ? <LivePulse /> : null}
      </div>
    </button>
  )
}

function ModeSection({
  mode,
  label,
  count,
  runs,
  activeRunId,
  roomy,
  projects,
  onDelete,
  test,
  emptyMessage,
}: {
  mode: 'training' | 'automatic'
  label: string
  count: number
  runs: RunSummary[]
  activeRunId: string | null
  roomy?: boolean
  projects?: Project[]
  onDelete: (run: RunSummary) => void
  test: RunTestGroup
  emptyMessage: string
}) {
  const [visibleCount, setVisibleCount] = useState(INITIAL_TEST_RUNS_VISIBLE)
  const effectiveVisible = minimumVisibleSectionRuns(runs, visibleCount, activeRunId)
  const visibleRuns = runs.slice(0, effectiveVisible)
  const remaining = runs.length - effectiveVisible
  const isExpandedBeyondDefault = visibleCount > INITIAL_TEST_RUNS_VISIBLE

  useEffect(() => {
    setVisibleCount(INITIAL_TEST_RUNS_VISIBLE)
  }, [runs.length])

  const accent =
    mode === 'training'
      ? 'border-warning/30 bg-warning/5'
      : 'border-brand-blue/30 bg-brand-blue/5'

  return (
    <div className={cn('rounded-md border border-l-[3px] py-1.5 px-1 space-y-px', accent)}>
      <button
        type="button"
        onClick={() => {
          if (isExpandedBeyondDefault) {
            setVisibleCount(INITIAL_TEST_RUNS_VISIBLE)
          }
        }}
        disabled={!isExpandedBeyondDefault}
        title={isExpandedBeyondDefault ? 'Show fewer attempts' : undefined}
        className={cn(
          'w-full px-2 pb-1 pt-0.5 text-left rounded-sm',
          isExpandedBeyondDefault
            ? 'hover:bg-accent/30 cursor-pointer'
            : 'cursor-default',
        )}
      >
        <span className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          {label} ({count})
        </span>
      </button>
      {runs.length === 0 ? (
        <p className="px-2 py-1.5 text-[11px] text-muted-foreground">{emptyMessage}</p>
      ) : (
        <>
          {visibleRuns.map((run) => {
            let sourceMeta: string | null = null
            if (run.use_replay_script && run.source_run_id) {
              sourceMeta = automaticSourceExistsInTest(run, test)
                ? `from ${run.source_run_id.slice(0, 8)}`
                : 'training removed'
            }
            return (
              <RunRow
                key={run.run_id}
                run={run}
                label={sectionAttemptLabel(run, runs)}
                active={activeRunId === run.run_id}
                roomy={roomy}
                projects={projects}
                onDelete={onDelete}
                sourceMeta={sourceMeta}
              />
            )
          })}
          {remaining > 0 ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 w-full justify-start px-2 text-[11px] text-muted-foreground hover:text-foreground"
              onClick={() =>
                setVisibleCount(nextVisibleTestRunCount(effectiveVisible, runs.length))
              }
            >
              Show {Math.min(remaining, TEST_RUNS_PAGE_SIZE)} more
            </Button>
          ) : null}
        </>
      )}
    </div>
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
  modeFilter: RunModeFilter
}

function TestGroupBlock({
  test,
  activeRunId,
  expanded,
  onToggle,
  onDelete,
  roomy = false,
  projects,
  modeFilter,
}: TestGroupBlockProps) {
  const containsActive = Boolean(
    activeRunId && test.runs.some((run) => run.run_id === activeRunId),
  )
  const trainingRuns = testTrainingRuns(test)
  const automaticRuns = testAutomaticRuns(test)
  const showTraining =
    modeFilter === 'training' || (modeFilter === 'all' && trainingRuns.length > 0)
  const showAutomatic =
    modeFilter === 'automatic' || (modeFilter === 'all' && automaticRuns.length > 0)

  return (
    <div className="space-y-px">
      <ThreadHeader
        title={test.title}
        level="group"
        expanded={expanded}
        onToggle={onToggle}
        hasLiveRun={testHasActiveRun(test)}
        containsActive={containsActive}
        collapseLabel="test"
      />
      <CollapsePanel expanded={expanded}>
        <div className={cn('space-y-2 py-1', CHILD_RAIL)}>
          {showTraining ? (
            <ModeSection
              mode="training"
              label="Training"
              count={trainingRuns.length}
              runs={trainingRuns}
              activeRunId={activeRunId}
              roomy={roomy}
              projects={projects}
              onDelete={onDelete}
              test={test}
              emptyMessage="No training runs yet"
            />
          ) : null}
          {showAutomatic ? (
            <ModeSection
              mode="automatic"
              label="Automatic"
              count={automaticRuns.length}
              runs={automaticRuns}
              activeRunId={activeRunId}
              roomy={roomy}
              projects={projects}
              onDelete={onDelete}
              test={test}
              emptyMessage="No automatic runs yet"
            />
          ) : null}
          {modeFilter === 'all' && trainingRuns.length === 0 && automaticRuns.length === 0 ? (
            <p className="px-2 py-1.5 text-[11px] text-muted-foreground">No runs yet</p>
          ) : null}
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
  modeFilter: RunModeFilter
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
  modeFilter,
}: ProjectThreadBlockProps) {
  const testGroups = thread.testGroups ?? []
  const containsActive = Boolean(
    activeRunId && thread.runs.some((run) => run.run_id === activeRunId),
  )
  const projectIcon = thread.uncategorized ? 'inbox' : 'globe'

  return (
    <div className="space-y-px">
      <ThreadHeader
        title={threadTitle(thread, projectNames)}
        level="project"
        projectIcon={projectIcon}
        expanded={expanded}
        onToggle={onToggle}
        hasLiveRun={threadHasActiveRun(thread)}
        containsActive={containsActive}
        collapseLabel={thread.uncategorized ? 'section' : 'project'}
      />
      <CollapsePanel expanded={expanded}>
        <div className={cn('space-y-px', CHILD_RAIL)}>
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
              modeFilter={modeFilter}
            />
          ))}
        </div>
      </CollapsePanel>
    </div>
  )
}

function testIdsForThread(thread: RunThread): string[] {
  return (thread.testGroups ?? []).map((test) => test.id)
}

function applyThreadToggle(prev: Set<string>, thread: RunThread): Set<string> {
  const next = new Set(prev)
  const testIds = testIdsForThread(thread)

  if (next.has(thread.id)) {
    next.delete(thread.id)
    for (const id of testIds) next.delete(id)
    return next
  }

  next.add(thread.id)
  for (const id of testIds) next.delete(id)
  return next
}

export default function RunThreadList({
  runs,
  activeRunId = null,
  variant = 'sidebar',
  limit,
  emptyMessage = 'No runs yet',
  projectNames = {},
  projects = [],
  modeFilter = 'all',
  rootsCollapsed = false,
  onRequestExpandRoots,
  expandAllToken = 0,
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
  const processedExpandAllToken = useRef(0)
  const skipNextAutoExpand = useRef(false)
  const prevRootsCollapsed = useRef(rootsCollapsed)
  const prevActiveRunId = useRef(activeRunId)

  useEffect(() => {
    if (rootsCollapsed && !prevRootsCollapsed.current) {
      setExpandedRoots(new Set())
    }
    prevRootsCollapsed.current = rootsCollapsed
  }, [rootsCollapsed])

  useEffect(() => {
    if (expandAllToken === 0 || expandAllToken === processedExpandAllToken.current) return
    processedExpandAllToken.current = expandAllToken
    setExpandedRoots(allThreadExpandIds(threads))
  }, [expandAllToken, threads])

  useEffect(() => {
    const activeRunChanged = prevActiveRunId.current !== activeRunId
    prevActiveRunId.current = activeRunId

    const needed = collectAutoExpandIds(threads, activeRunId)

    if (activeRunId && rootsCollapsed && activeRunChanged) {
      onRequestExpandRoots?.()
    }

    if (rootsCollapsed) return

    if (skipNextAutoExpand.current) {
      skipNextAutoExpand.current = false
      return
    }

    setExpandedRoots((prev) => {
      const next = new Set(prev)
      for (const id of needed) next.add(id)
      return next
    })
  }, [threads, activeRunId, rootsCollapsed, onRequestExpandRoots])

  function toggleThreadExpanded(thread: RunThread) {
    setExpandedRoots((prev) => applyThreadToggle(prev, thread))
  }

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
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
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

  const deleteKeepsDependents =
    deleteTarget &&
    !deleteTarget.use_replay_script &&
    hasAutomaticDependents(deleteTarget.run_id, runs)

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
          const expanded = !rootsCollapsed && expandedRoots.has(thread.id)

          return (
            <ProjectThreadBlock
              key={thread.id}
              thread={thread}
              activeRunId={activeRunId}
              expanded={expanded}
              onToggle={() => {
                if (rootsCollapsed) {
                  skipNextAutoExpand.current = true
                  onRequestExpandRoots?.()
                  setExpandedRoots((prev) => applyThreadToggle(prev, thread))
                  return
                }
                toggleThreadExpanded(thread)
              }}
              expandedTests={expandedRoots}
              onToggleTest={toggleExpanded}
              onDelete={setDeleteTarget}
              projectNames={projectNames}
              roomy={roomy}
              projects={projects}
              modeFilter={modeFilter}
            />
          )
        })}
      </div>

      <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this run?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteKeepsDependents
                ? 'This removes the training run from your list. Automatic runs that used this training stay in the list. Their replay script is kept so you can still re-run them.'
                : deleteTarget?.use_replay_script
                  ? 'This permanently removes the automatic run and its saved history and report.'
                  : 'This permanently removes the run and its saved history, replay script (if unused), and report.'}
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

export { StatusDot }
