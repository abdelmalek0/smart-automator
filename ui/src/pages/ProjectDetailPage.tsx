import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  FileText,
  Link2,
  Loader2,
  MoreHorizontal,
  PenLine,
  Plus,
  Settings2,
  Trash2,
  Upload,
} from 'lucide-react'
import { listRuns } from '@/api'
import SuiteProgressPanel from '@/components/projects/SuiteProgressPanel'
import ProjectRunsPanel from '@/components/projects/ProjectRunsPanel'
import ProjectTestsPanel from '@/components/projects/ProjectTestsPanel'
import ConnectOfflineNotice from '@/components/ConnectOfflineNotice'
import TestEditorDialog from '@/components/TestEditorDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
import { useProjectSuiteRunner } from '@/hooks/useProjectSuiteRunner'
import { useRunStartGate } from '@/hooks/useRunStartGate'
import { useProjects } from '@/hooks/useProjects'
import { startProjectTaskRun } from '@/lib/project-run'
import { parseProjectTestsPack } from '@/lib/project-tests-pack'
import {
  countNeverRunTests,
  latestRunsByProjectTaskId,
} from '@/lib/project-task-status'
import {
  getProjectCardStats,
  PROJECT_ACCENT_CLASSES,
  projectAccentIndex,
  projectInitials,
} from '@/lib/project-view'
import type { Project, ProjectTask } from '@/types'
import { cn } from '@/lib/utils'

export default function ProjectDetailPage() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const {
    projects,
    isLoading,
    updateProject,
    deleteProject,
    addTaskToProject,
    updateProjectTask,
    removeTaskFromProject,
    importProjectTests,
    isUpdating,
    isDeleting,
    isRemovingTask,
    isImportingTests,
  } = useProjects()
  const suite = useProjectSuiteRunner()
  const runStartGate = useRunStartGate()
  const { data: runs = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: listRuns,
  })

  const project = projects.find((p) => p.id === projectId) ?? null
  const [runningId, setRunningId] = useState<string | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [excludedTaskIds, setExcludedTaskIds] = useState<Set<string>>(() => new Set())
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorMode, setEditorMode] = useState<'edit' | 'create'>('edit')
  const [editorTask, setEditorTask] = useState<ProjectTask | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [editingDescription, setEditingDescription] = useState(false)
  const [descriptionDraft, setDescriptionDraft] = useState('')
  const [savingDescription, setSavingDescription] = useState(false)
  const [urlDraft, setUrlDraft] = useState('')
  const [contextDraft, setContextDraft] = useState('')
  const [editingConfig, setEditingConfig] = useState(false)
  const [savingConfig, setSavingConfig] = useState(false)
  const [configError, setConfigError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState('configuration')
  const [importPackError, setImportPackError] = useState<string | null>(null)
  const importFileRef = useRef<HTMLInputElement>(null)

  const suiteBusy = Boolean(project && suite.isRunning && suite.state.projectId === project.id)
  const suiteActive = Boolean(
    project && suite.state.phase !== 'idle' && suite.state.projectId === project.id,
  )
  const anySuiteRunning = suite.isRunning
  const runActionsBlocked = !runStartGate.canStartRun
  const connectOffline = runStartGate.blockReason === 'offline'
  const runGateHint =
    runActionsBlocked && runStartGate.blockReason === 'busy'
      ? (runStartGate.blockHint ?? undefined)
      : undefined
  const stats = project ? getProjectCardStats(project) : null
  const latestByTask = useMemo(
    () => (project ? latestRunsByProjectTaskId(runs, project.id) : new Map()),
    [project, runs],
  )
  const neverRunCount = project ? countNeverRunTests(project.tasks, latestByTask) : 0
  const projectAccent = project
    ? PROJECT_ACCENT_CLASSES[projectAccentIndex(project.id || project.name)]
    : PROJECT_ACCENT_CLASSES[0]

  // On opening a project: Runs if a suite is running, otherwise Configuration.
  useEffect(() => {
    if (!project) return
    setActiveTab(
      suite.isRunning && suite.state.projectId === project.id ? 'runs' : 'configuration',
    )
    // Only when landing on / switching between projects — not on every suite phase change.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: project.id only
  }, [project?.id])

  // Drop exclusions for tests that no longer exist.
  useEffect(() => {
    if (!project) return
    const validIds = new Set(project.tasks.map((t) => t.id))
    setExcludedTaskIds((prev) => {
      let changed = false
      const next = new Set<string>()
      for (const id of prev) {
        if (validIds.has(id)) next.add(id)
        else changed = true
      }
      return changed ? next : prev
    })
  }, [project])

  const includedTaskIds = useMemo(() => {
    if (!project) return []
    return project.tasks.filter((t) => !excludedTaskIds.has(t.id)).map((t) => t.id)
  }, [project, excludedTaskIds])

  const includedCount = includedTaskIds.length
  const allIncluded = Boolean(project && includedCount === project.tasks.length)
  const noneIncluded = includedCount === 0
  const includedTrainedCount = useMemo(() => {
    if (!project) return 0
    return project.tasks.filter(
      (t) => !excludedTaskIds.has(t.id) && t.has_trained_replay,
    ).length
  }, [project, excludedTaskIds])
  const noneTrainedIncluded = includedTrainedCount === 0

  function handleRunAll() {
    if (!project || noneIncluded) return
    setActiveTab('runs')
    void suite.runAll(project, {
      taskIds: allIncluded ? undefined : includedTaskIds,
    })
  }

  function handleRetrainAll() {
    if (!project || noneTrainedIncluded) return
    const trainedTaskIds = project.tasks
      .filter((t) => !excludedTaskIds.has(t.id) && t.has_trained_replay)
      .map((t) => t.id)
    if (trainedTaskIds.length === 0) return
    setActiveTab('runs')
    void suite.runAll(project, {
      taskIds: trainedTaskIds,
      forceTraining: true,
    })
  }

  function setTaskIncluded(taskId: string, included: boolean) {
    setExcludedTaskIds((prev) => {
      const next = new Set(prev)
      if (included) next.delete(taskId)
      else next.add(taskId)
      return next
    })
  }

  function selectAllTests() {
    setExcludedTaskIds(new Set())
  }

  function selectNoneTests() {
    if (!project) return
    setExcludedTaskIds(new Set(project.tasks.map((t) => t.id)))
  }

  async function handleImportTestsFile(file: File) {
    if (!project) return
    setImportPackError(null)
    setActiveTab('tests')
    try {
      const text = await file.text()
      let parsed: unknown
      try {
        parsed = JSON.parse(text)
      } catch {
        throw new Error('Invalid tests file')
      }
      const pack = parseProjectTestsPack(parsed)
      await importProjectTests({ projectId: project.id, pack })
    } catch (err) {
      setImportPackError(err instanceof Error ? err.message : 'Could not import tests')
    } finally {
      if (importFileRef.current) {
        importFileRef.current.value = ''
      }
    }
  }

  function openImportTests() {
    setImportPackError(null)
    importFileRef.current?.click()
  }

  async function handleRunTask(proj: Project, task: ProjectTask) {
    setRunningId(task.id)
    setRunError(null)
    try {
      const run = await startProjectTaskRun(proj, task)
      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/runs/${run.run_id}`)
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'Failed to start run')
    } finally {
      setRunningId(null)
    }
  }

  async function handleRetrainTask(proj: Project, task: ProjectTask) {
    setRunningId(task.id)
    setRunError(null)
    try {
      const run = await startProjectTaskRun(proj, task, { forceTraining: true })
      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/runs/${run.run_id}`)
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'Failed to start run')
    } finally {
      setRunningId(null)
    }
  }

  async function handleTrainManually(proj: Project, task: ProjectTask) {
    setRunningId(task.id)
    setRunError(null)
    try {
      const run = await startProjectTaskRun(proj, task, { forceManual: true })
      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/runs/${run.run_id}`)
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'Failed to start run')
    } finally {
      setRunningId(null)
    }
  }

  function openEditTask(task: ProjectTask) {
    setEditorTask(task)
    setEditorMode('edit')
    setEditorOpen(true)
  }

  function openAddTask() {
    setEditorTask(null)
    setEditorMode('create')
    setEditorOpen(true)
    setActiveTab('tests')
  }

  async function handleSaveTask(payload: {
    projectId: string
    taskId?: string
    name?: string | null
    task: string
    success_criteria: string
    headless: boolean
    max_steps: number
    cdp_url?: string
    fresh_profile?: boolean
  }) {
    if (payload.taskId) {
      await updateProjectTask({
        projectId: payload.projectId,
        taskId: payload.taskId,
        name: payload.name,
        task: payload.task,
        success_criteria: payload.success_criteria,
        headless: payload.headless,
        max_steps: payload.max_steps,
        cdp_url: payload.cdp_url,
        fresh_profile: payload.fresh_profile,
      })
      return
    }
    return addTaskToProject({
      projectId: payload.projectId,
      name: payload.name,
      task: payload.task,
      success_criteria: payload.success_criteria,
      headless: payload.headless,
      max_steps: payload.max_steps,
      cdp_url: payload.cdp_url,
      fresh_profile: payload.fresh_profile,
    })
  }

  function startRename() {
    if (!project) return
    setNameDraft(project.name)
    setRenaming(true)
  }

  async function saveRename() {
    if (!project) return
    const next = nameDraft.trim()
    if (!next || next === project.name) {
      setRenaming(false)
      return
    }
    await updateProject({ projectId: project.id, name: next })
    setRenaming(false)
  }

  function startEditDescription() {
    if (!project) return
    setDescriptionDraft(project.description ?? '')
    setEditingDescription(true)
  }

  async function saveDescription() {
    if (!project) return
    const next = descriptionDraft.trim()
    if (next === (project.description ?? '').trim()) {
      setEditingDescription(false)
      return
    }
    setSavingDescription(true)
    try {
      await updateProject({ projectId: project.id, description: next })
      setEditingDescription(false)
    } finally {
      setSavingDescription(false)
    }
  }

  function startEditConfig() {
    if (!project) return
    setUrlDraft(project.url ?? '')
    setContextDraft(project.context_prompt)
    setConfigError(null)
    setEditingConfig(true)
    setActiveTab('configuration')
  }

  async function saveConfig() {
    if (!project) return
    setSavingConfig(true)
    setConfigError(null)
    try {
      await updateProject({
        projectId: project.id,
        url: urlDraft.trim(),
        context_prompt: contextDraft,
      })
      setEditingConfig(false)
    } catch (err) {
      setConfigError(err instanceof Error ? err.message : 'Failed to save configuration')
    } finally {
      setSavingConfig(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading project…
      </div>
    )
  }

  if (!project) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
        <div className="space-y-1.5">
          <h2 className="text-lg font-semibold">Project not found</h2>
          <p className="text-sm text-muted-foreground max-w-sm">
            This project may have been deleted or the link is invalid.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to="/projects">
            <ArrowLeft className="h-4 w-4" />
            Back to projects
          </Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <input
        ref={importFileRef}
        type="file"
        accept="application/json,.json"
        className="sr-only"
        aria-label="Import tests JSON"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) {
            void handleImportTestsFile(file)
          }
        }}
      />
      <div className="flex-shrink-0 border-b border-border/60 px-4 sm:px-6 pt-5 pb-4">
        <div className="mx-auto w-full max-w-3xl space-y-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Link
              to="/projects"
              className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 -ml-1.5 hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Projects
            </Link>
            <span aria-hidden className="text-muted-foreground/50">
              /
            </span>
            <span className="truncate text-foreground/80">{project.name}</span>
          </div>

          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3 min-w-0">
              <div
                className={cn(
                  'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-sm font-semibold',
                  projectAccent,
                )}
                aria-hidden
              >
                {projectInitials(project.name).slice(0, 1)}
              </div>
              <div className="min-w-0 space-y-1">
                {renaming ? (
                  <form
                    className="flex flex-wrap gap-2 items-center"
                    onSubmit={(e) => {
                      e.preventDefault()
                      void saveRename()
                    }}
                  >
                    <Input
                      value={nameDraft}
                      onChange={(e) => setNameDraft(e.target.value)}
                      className="h-9 max-w-xs"
                      autoFocus
                      aria-label="Project name"
                      disabled={isUpdating}
                    />
                    <Button type="submit" size="sm" disabled={isUpdating || !nameDraft.trim()}>
                      {isUpdating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => setRenaming(false)}
                    >
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <h1 className="text-2xl font-semibold tracking-tight truncate">{project.name}</h1>
                )}
                {editingDescription ? (
                  <form
                    className="space-y-2 max-w-xl"
                    onSubmit={(e) => {
                      e.preventDefault()
                      void saveDescription()
                    }}
                  >
                    <Textarea
                      value={descriptionDraft}
                      onChange={(e) => setDescriptionDraft(e.target.value)}
                      rows={2}
                      autoFocus
                      placeholder="Short description for this project…"
                      aria-label="Project description"
                      disabled={savingDescription}
                      className="text-sm"
                    />
                    <div className="flex gap-2">
                      <Button
                        type="submit"
                        size="sm"
                        disabled={savingDescription}
                      >
                        {savingDescription ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : null}
                        Save
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={savingDescription}
                        onClick={() => setEditingDescription(false)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={startEditDescription}
                    className={cn(
                      'block w-full text-left text-sm leading-snug rounded-md -ml-1 px-1 py-0.5',
                      'hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      project.description?.trim()
                        ? 'text-muted-foreground'
                        : 'text-muted-foreground/60 italic',
                    )}
                    aria-label="Edit project description"
                  >
                    {project.description?.trim() || 'Add a description…'}
                  </button>
                )}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  {stats?.hasUrl ? (
                    <span className="inline-flex items-center gap-1 min-w-0">
                      <Link2 className="h-3 w-3 shrink-0" aria-hidden />
                      <span className="mono truncate max-w-[28rem]">{project.url}</span>
                    </span>
                  ) : (
                    <span>
                      {stats?.testCount ?? 0} test{(stats?.testCount ?? 0) !== 1 ? 's' : ''}
                      {(stats?.trainedCount ?? 0) > 0
                        ? ` · ${stats?.trainedCount} trained`
                        : ''}
                      {neverRunCount > 0 && (stats?.testCount ?? 0) > 0
                        ? ` · ${neverRunCount} never run`
                        : ''}
                    </span>
                  )}
                  {stats?.hasNotes && (
                    <span className="inline-flex items-center gap-1">
                      <FileText className="h-3 w-3" aria-hidden />
                      Project context
                    </span>
                  )}
                  {suiteActive && activeTab !== 'runs' && (
                    <button
                      type="button"
                      onClick={() => setActiveTab('runs')}
                      className={cn(
                        'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 -ml-1',
                        'text-primary hover:bg-primary/10 transition-colors',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      )}
                    >
                      {suiteBusy ? (
                        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                      ) : null}
                      {suiteBusy ? 'Suite running — view' : 'Suite results — view'}
                    </button>
                  )}
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <Button
                size="sm"
                variant="outline"
                className="rounded-full"
                onClick={openAddTask}
                disabled={suiteBusy}
              >
                <Plus className="h-3.5 w-3.5" />
                Add test
              </Button>
              <AlertDialog>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-8 w-8"
                      aria-label="Project actions"
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={startRename}>
                      <PenLine className="h-4 w-4" />
                      Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={startEditDescription}>
                      <FileText className="h-4 w-4" />
                      Edit description
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={startEditConfig}>
                      <Settings2 className="h-4 w-4" />
                      Edit configuration
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={openImportTests}
                      disabled={isImportingTests || suiteBusy}
                    >
                      {isImportingTests ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Upload className="h-4 w-4" />
                      )}
                      Import tests
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <AlertDialogTrigger asChild>
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onSelect={(e) => e.preventDefault()}
                      >
                        <Trash2 className="h-4 w-4" />
                        Delete project
                      </DropdownMenuItem>
                    </AlertDialogTrigger>
                  </DropdownMenuContent>
                </DropdownMenu>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete &quot;{project.name}&quot;?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This removes the project, its project context, and all saved tests.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      disabled={isDeleting}
                      onClick={() => {
                        void deleteProject(project.id).then(() => navigate('/projects'))
                      }}
                    >
                      {isDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      Delete
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 py-5">
          {connectOffline && (
            <ConnectOfflineNotice
              message={runStartGate.blockHint ?? undefined}
              className="mb-4"
            />
          )}
          {runError && (
            <p className="mb-4 text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-md px-3 py-2">
              {runError}
            </p>
          )}
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList>
              <TabsTrigger value="configuration">Configuration</TabsTrigger>
              <TabsTrigger value="tests">Tests</TabsTrigger>
              <TabsTrigger value="runs" className="gap-1.5">
                Runs
                {suiteActive && (
                  <span
                    className={cn(
                      'inline-flex h-1.5 w-1.5 rounded-full',
                      suiteBusy ? 'bg-primary animate-pulse' : 'bg-primary/70',
                    )}
                    aria-hidden
                  />
                )}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="configuration" className="mt-4">
              <div className="rounded-xl border border-border/80 bg-card/60 p-4 sm:p-5 space-y-4 animate-in fade-in-0 duration-300">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold">Project configuration</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Shared URL and project context injected into every test in this project.
                    </p>
                  </div>
                  {!editingConfig && (
                    <Button size="sm" variant="outline" onClick={startEditConfig}>
                      {stats?.isConfigured ? 'Edit' : 'Add configuration'}
                    </Button>
                  )}
                </div>

                {editingConfig ? (
                  <div className="space-y-3">
                    <div className="space-y-1.5">
                      <Label htmlFor={`url-${project.id}`}>URL</Label>
                      <Input
                        id={`url-${project.id}`}
                        value={urlDraft}
                        onChange={(e) => setUrlDraft(e.target.value)}
                        placeholder="https://app.example.com"
                        className="mono text-sm"
                        disabled={savingConfig}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`notes-${project.id}`}>Project context</Label>
                      <Textarea
                        id={`notes-${project.id}`}
                        value={contextDraft}
                        onChange={(e) => setContextDraft(e.target.value)}
                        placeholder={
                          'Login: admin@example.com / password123\nDefault store: Downtown\nTest card: 4242...'
                        }
                        rows={5}
                        disabled={savingConfig}
                      />
                    </div>
                    {configError && <p className="text-sm text-destructive">{configError}</p>}
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => void saveConfig()} disabled={savingConfig}>
                        {savingConfig ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                        Save
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={savingConfig}
                        onClick={() => setEditingConfig(false)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-muted-foreground">URL</p>
                      {project.url ? (
                        <p className="text-sm mono text-primary break-all">{project.url}</p>
                      ) : (
                        <p className="text-sm text-muted-foreground italic">No URL set</p>
                      )}
                    </div>
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-muted-foreground">Project context</p>
                      {project.context_prompt ? (
                        <pre className="rounded-lg border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground whitespace-pre-wrap font-sans leading-relaxed">
                          {project.context_prompt}
                        </pre>
                      ) : (
                        <p className="text-sm text-muted-foreground italic">No project context yet.</p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </TabsContent>

            <TabsContent value="tests" className="mt-4">
              <ProjectTestsPanel
                project={project}
                suite={suite}
                suiteBusy={suiteBusy}
                excludedTaskIds={excludedTaskIds}
                runningId={runningId}
                anySuiteRunning={anySuiteRunning}
                runActionsBlocked={runActionsBlocked}
                runGateHint={runGateHint}
                isRemovingTask={isRemovingTask}
                isImportingTests={isImportingTests}
                importError={importPackError}
                allIncluded={allIncluded}
                includedCount={includedCount}
                noneIncluded={noneIncluded}
                includedTrainedCount={includedTrainedCount}
                noneTrainedIncluded={noneTrainedIncluded}
                onRunAll={handleRunAll}
                onRetrainAll={handleRetrainAll}
                onAddTest={openAddTask}
                onImportClick={openImportTests}
                onSetTaskIncluded={setTaskIncluded}
                onSelectAll={selectAllTests}
                onSelectNone={selectNoneTests}
                onRunTask={(proj, task) => void handleRunTask(proj, task)}
                onRetrainTask={(proj, task) => void handleRetrainTask(proj, task)}
                onTrainManually={(proj, task) => void handleTrainManually(proj, task)}
                onEditTask={openEditTask}
                onDeleteTask={(taskId) =>
                  void removeTaskFromProject({ projectId: project.id, taskId })
                }
              />
            </TabsContent>

            <TabsContent value="runs" className="mt-4">
              {suiteActive ? (
                <SuiteProgressPanel project={project} suite={suite} />
              ) : (
                <ProjectRunsPanel project={project} runs={runs} />
              )}
            </TabsContent>
          </Tabs>
        </div>
      </ScrollArea>

      <TestEditorDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        projectId={project.id}
        task={
          editorMode === 'edit'
            ? (project.tasks.find((t) => t.id === editorTask?.id) ?? editorTask)
            : null
        }
        mode={editorMode}
        onSaveTask={handleSaveTask}
        onStartManualRun={async (task) => {
          await handleTrainManually(project, task)
        }}
      />
    </div>
  )
}
