import { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Play,
  Plus,
  Trash2,
} from 'lucide-react'
import SuiteProgressPanel from '@/components/projects/SuiteProgressPanel'
import TestRow from '@/components/projects/TestRow'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import type { ProjectSuiteRunner } from '@/hooks/useProjectSuiteRunner'
import type { Project, ProjectTask } from '@/types'

interface Props {
  project: Project
  expanded: boolean
  onToggleExpand: () => void
  suite: ProjectSuiteRunner
  singleRunningId: string | null
  onRunTask: (task: ProjectTask) => void
  onEditTask: (task: ProjectTask) => void
  onAddTask: () => void
  onDeleteTask: (taskId: string) => void
  onUpdateProject: (payload: {
    projectId: string
    name?: string
    url?: string
    context_prompt?: string
  }) => Promise<unknown>
  onDeleteProject: () => void
}

export default function ProjectCard({
  project,
  expanded,
  onToggleExpand,
  suite,
  singleRunningId,
  onRunTask,
  onEditTask,
  onAddTask,
  onDeleteTask,
  onUpdateProject,
  onDeleteProject,
}: Props) {
  const suiteBusy = suite.isRunning && suite.state.projectId === project.id
  const anySuiteRunning = suite.isRunning
  const [editingContext, setEditingContext] = useState(false)
  const [urlDraft, setUrlDraft] = useState(project.url ?? '')
  const [contextDraft, setContextDraft] = useState(project.context_prompt)
  const [renaming, setRenaming] = useState(false)
  const [nameDraft, setNameDraft] = useState(project.name)
  const [savingName, setSavingName] = useState(false)

  function startEditContext() {
    setUrlDraft(project.url ?? '')
    setContextDraft(project.context_prompt)
    setEditingContext(true)
    if (!expanded) onToggleExpand()
  }

  async function saveContext() {
    await onUpdateProject({
      projectId: project.id,
      url: urlDraft.trim(),
      context_prompt: contextDraft,
    })
    setEditingContext(false)
  }

  function startRename() {
    setNameDraft(project.name)
    setRenaming(true)
  }

  async function saveRename() {
    const next = nameDraft.trim()
    if (!next || next === project.name) {
      setRenaming(false)
      return
    }
    setSavingName(true)
    try {
      await onUpdateProject({ projectId: project.id, name: next })
      setRenaming(false)
    } finally {
      setSavingName(false)
    }
  }

  return (
    <Card>
      <CardHeader className="py-3 px-4">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onToggleExpand}
            className="text-muted-foreground hover:text-foreground"
            aria-expanded={expanded}
          >
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
          <div className="flex-1 min-w-0">
            {renaming ? (
              <form
                className="flex gap-2 items-center"
                onSubmit={(e) => {
                  e.preventDefault()
                  void saveRename()
                }}
              >
                <Input
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  className="h-8 text-sm"
                  autoFocus
                  onBlur={() => void saveRename()}
                />
                <Button type="submit" size="sm" disabled={savingName || !nameDraft.trim()}>
                  {savingName ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save'}
                </Button>
              </form>
            ) : (
              <>
                <CardTitle className="text-sm">{project.name}</CardTitle>
                <CardDescription className="text-xs truncate">
                  {project.tasks.length} test{project.tasks.length !== 1 ? 's' : ''}
                  {project.url && <span className="mono ml-1">· {project.url}</span>}
                  {!project.url && project.context_prompt && ' · notes configured'}
                </CardDescription>
              </>
            )}
          </div>
          {project.tasks.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              disabled={anySuiteRunning || singleRunningId !== null}
              onClick={() => void suite.runAll(project)}
            >
              {suiteBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Run All
            </Button>
          )}
          <AlertDialog>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={startRename}>Rename</DropdownMenuItem>
                <DropdownMenuItem onClick={startEditContext}>Edit context</DropdownMenuItem>
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
                <AlertDialogAction onClick={onDeleteProject}>Delete</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="px-4 pb-4 pt-0 space-y-4">
          <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-3">
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">
              Project configuration
            </Label>
            {editingContext ? (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor={`url-${project.id}`} className="text-xs">
                    URL
                  </Label>
                  <Input
                    id={`url-${project.id}`}
                    value={urlDraft}
                    onChange={(e) => setUrlDraft(e.target.value)}
                    placeholder="https://app.example.com"
                    className="mono text-sm"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`notes-${project.id}`} className="text-xs">
                    Site notes
                  </Label>
                  <Textarea
                    id={`notes-${project.id}`}
                    value={contextDraft}
                    onChange={(e) => setContextDraft(e.target.value)}
                    placeholder="Login: admin@example.com / password123&#10;Default store: Downtown&#10;Test card: 4242..."
                    rows={4}
                    className="text-sm"
                  />
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => void saveContext()}>
                    Save
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditingContext(false)}>
                    Cancel
                  </Button>
                </div>
              </>
            ) : (
              <>
                {project.url ? (
                  <p className="text-xs mono text-primary break-all">{project.url}</p>
                ) : (
                  <p className="text-xs text-muted-foreground italic">No URL set</p>
                )}
                {project.context_prompt ? (
                  <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-sans leading-relaxed">
                    {project.context_prompt}
                  </pre>
                ) : (
                  <p className="text-xs text-muted-foreground italic">No site notes yet.</p>
                )}
                <Button size="sm" variant="outline" onClick={startEditContext}>
                  {project.url || project.context_prompt ? 'Edit configuration' : 'Add configuration'}
                </Button>
              </>
            )}
          </div>

          <SuiteProgressPanel project={project} suite={suite} />

          <div className="flex items-center justify-between gap-2">
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">Tests</Label>
            <Button size="sm" variant="outline" onClick={onAddTask} disabled={suiteBusy}>
              <Plus className="h-3.5 w-3.5" />
              Add test
            </Button>
          </div>

          {project.tasks.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center space-y-3">
              <p className="text-sm text-muted-foreground">
                No tests yet. Add one here or save a run to this project from New Run.
              </p>
              <Button size="sm" onClick={onAddTask}>
                <Plus className="h-3.5 w-3.5" />
                Add test
              </Button>
            </div>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {project.tasks.map((task) => (
                <TestRow
                  key={task.id}
                  task={task}
                  suiteResult={
                    suite.state.projectId === project.id
                      ? suite.resultFor(task.id)
                      : undefined
                  }
                  running={singleRunningId === task.id}
                  disabled={anySuiteRunning || (singleRunningId !== null && singleRunningId !== task.id)}
                  onRun={() => onRunTask(task)}
                  onEdit={() => onEditTask(task)}
                  onDelete={() => onDeleteTask(task.id)}
                />
              ))}
            </ul>
          )}
        </CardContent>
      )}
    </Card>
  )
}
