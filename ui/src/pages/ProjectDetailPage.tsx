import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  FileText,
  Link2,
  Loader2,
  MoreHorizontal,
  Play,
  Plus,
  Settings2,
  Trash2,
} from 'lucide-react'
import SuiteProgressPanel from '@/components/projects/SuiteProgressPanel'
import TestRow from '@/components/projects/TestRow'
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
import { useProjects } from '@/hooks/useProjects'
import { startProjectTaskRun } from '@/lib/project-run'
import { getProjectCardStats, projectInitials } from '@/lib/project-view'
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
    isUpdating,
    isDeleting,
    isRemovingTask,
  } = useProjects()
  const suite = useProjectSuiteRunner()

  const project = projects.find((p) => p.id === projectId) ?? null
  const [runningId, setRunningId] = useState<string | null>(null)
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

  const suiteBusy = Boolean(project && suite.isRunning && suite.state.projectId === project.id)
  const suiteActive = Boolean(
    project && suite.state.phase !== 'idle' && suite.state.projectId === project.id,
  )
  const anySuiteRunning = suite.isRunning
  const stats = project ? getProjectCardStats(project) : null

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

  function handleRunAll() {
    if (!project || noneIncluded) return
    setActiveTab('runs')
    void suite.runAll(project, {
      taskIds: allIncluded ? undefined : includedTaskIds,
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

  async function handleRunTask(proj: Project, task: ProjectTask) {
    setRunningId(task.id)
    try {
      const run = await startProjectTaskRun(proj, task)
      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/runs/${run.run_id}`)
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
    } else {
      await addTaskToProject({
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
                  'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
                  'bg-primary/15 text-primary text-sm font-semibold',
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
                    </span>
                  )}
                  {stats?.hasNotes && (
                    <span className="inline-flex items-center gap-1">
                      <FileText className="h-3 w-3" aria-hidden />
                      Notes
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
              {project.tasks.length > 0 && (
                <Button
                  size="sm"
                  disabled={anySuiteRunning || runningId !== null || noneIncluded}
                  onClick={handleRunAll}
                >
                  {suiteBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  {allIncluded ? 'Run All' : `Run ${includedCount}`}
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={openAddTask} disabled={suiteBusy}>
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
                    <DropdownMenuItem onClick={startRename}>Rename</DropdownMenuItem>
                    <DropdownMenuItem onClick={startEditDescription}>
                      Edit description
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={startEditConfig}>
                      <Settings2 className="h-4 w-4" />
                      Edit configuration
                    </DropdownMenuItem>
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
                      This removes the project, its context prompt, and all saved tests.
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
                      Shared URL and site notes injected into every test in this project.
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
                      <Label htmlFor={`notes-${project.id}`}>Site notes</Label>
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
                  <div className="space-y-3">
                    {project.url ? (
                      <p className="text-sm mono text-primary break-all">{project.url}</p>
                    ) : (
                      <p className="text-sm text-muted-foreground italic">No URL set</p>
                    )}
                    {project.context_prompt ? (
                      <pre className="rounded-lg border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground whitespace-pre-wrap font-sans leading-relaxed">
                        {project.context_prompt}
                      </pre>
                    ) : (
                      <p className="text-sm text-muted-foreground italic">No site notes yet.</p>
                    )}
                  </div>
                )}
              </div>
            </TabsContent>

            <TabsContent value="tests" className="space-y-4 mt-4">
              {project.tasks.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border px-4 py-12 text-center space-y-3 animate-in fade-in-0 duration-300">
                  <p className="text-sm text-muted-foreground max-w-md mx-auto">
                    No tests yet. Add one here or save a run to this project from New Run.
                  </p>
                  <Button size="sm" onClick={openAddTask}>
                    <Plus className="h-3.5 w-3.5" />
                    Add test
                  </Button>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 px-0.5">
                    <p className="text-xs text-muted-foreground">
                      {includedCount} of {project.tasks.length} selected for Run All
                      {!allIncluded && (
                        <span className="text-muted-foreground/80">
                          {' '}
                          · uncheck tests to exclude them
                        </span>
                      )}
                    </p>
                    <div className="flex items-center gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        disabled={suiteBusy || allIncluded}
                        onClick={selectAllTests}
                      >
                        Select all
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        disabled={suiteBusy || noneIncluded}
                        onClick={selectNoneTests}
                      >
                        Select none
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-2" role="list">
                    {project.tasks.map((task, index) => (
                      <div
                        key={task.id}
                        className="animate-in fade-in-0 slide-in-from-bottom-1 duration-300"
                        style={{ animationDelay: `${Math.min(index, 10) * 30}ms` }}
                        role="listitem"
                      >
                        <TestRow
                          task={task}
                          running={runningId === task.id}
                          disabled={
                            anySuiteRunning || (runningId !== null && runningId !== task.id)
                          }
                          deleting={isRemovingTask}
                          includedInSuite={!excludedTaskIds.has(task.id)}
                          onIncludedInSuiteChange={(included) =>
                            setTaskIncluded(task.id, included)
                          }
                          onRun={() => void handleRunTask(project, task)}
                          onEdit={() => openEditTask(task)}
                          onDelete={() =>
                            void removeTaskFromProject({ projectId: project.id, taskId: task.id })
                          }
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </TabsContent>

            <TabsContent value="runs" className="mt-4 space-y-4">
              {suiteActive ? (
                <SuiteProgressPanel project={project} suite={suite} />
              ) : (
                <div className="rounded-xl border border-dashed border-border px-4 py-14 text-center space-y-3 animate-in fade-in-0 duration-300">
                  <p className="text-sm font-medium">No suite in progress</p>
                  <p className="text-sm text-muted-foreground max-w-sm mx-auto">
                    Run a suite to see live progress and results here. Select which tests to include
                    on the Tests tab.
                  </p>
                  {project.tasks.length > 0 && (
                    <Button
                      size="sm"
                      disabled={anySuiteRunning || runningId !== null || noneIncluded}
                      onClick={handleRunAll}
                    >
                      <Play className="h-3.5 w-3.5" />
                      {allIncluded ? 'Run All' : `Run ${includedCount}`}
                    </Button>
                  )}
                </div>
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
      />
    </div>
  )
}
