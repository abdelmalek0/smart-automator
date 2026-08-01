import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Globe, Loader2, Plus } from 'lucide-react'
import ProjectCard from '@/components/projects/ProjectCard'
import TestEditorDialog from '@/components/TestEditorDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useProjectSuiteRunner } from '@/hooks/useProjectSuiteRunner'
import { useProjects } from '@/hooks/useProjects'
import { startProjectTaskRun } from '@/lib/project-run'
import type { Project, ProjectTask } from '@/types'

export default function ProjectsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const {
    projects,
    isLoading,
    createProject,
    updateProject,
    deleteProject,
    addTaskToProject,
    updateProjectTask,
    removeTaskFromProject,
  } = useProjects()
  const suite = useProjectSuiteRunner()

  const [newName, setNewName] = useState('')
  const [runningId, setRunningId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(
    () => (suite.state.phase !== 'idle' ? suite.state.projectId : null),
  )

  // Re-expand the suite project when returning to this tab with live/completed progress.
  useEffect(() => {
    if (suite.state.phase !== 'idle' && suite.state.projectId) {
      setExpandedId(suite.state.projectId)
    }
  }, [suite.state.phase, suite.state.projectId])

  const [editorOpen, setEditorOpen] = useState(false)
  const [editorMode, setEditorMode] = useState<'edit' | 'create'>('edit')
  const [editorProjectId, setEditorProjectId] = useState<string | null>(null)
  const [editorTask, setEditorTask] = useState<ProjectTask | null>(null)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    const project = await createProject({ name: newName.trim() })
    setNewName('')
    setExpandedId(project.id)
  }

  async function handleRunTask(project: Project, task: ProjectTask) {
    setRunningId(task.id)
    try {
      const run = await startProjectTaskRun(project, task)
      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/runs/${run.run_id}`)
    } finally {
      setRunningId(null)
    }
  }

  function openEditTask(project: Project, task: ProjectTask) {
    setEditorProjectId(project.id)
    setEditorTask(task)
    setEditorMode('edit')
    setEditorOpen(true)
  }

  function openAddTask(project: Project) {
    setEditorProjectId(project.id)
    setEditorTask(null)
    setEditorMode('create')
    setEditorOpen(true)
    setExpandedId(project.id)
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

  const editorProject = projects.find((p) => p.id === editorProjectId) ?? null

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 px-6 pt-6 pb-4 border-b border-border">
        <div className="flex items-center gap-2 mb-1">
          <Globe className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Projects</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Group tests by project. Edit prompts and trained steps, then run them one-by-one or as a
          sequential suite.
        </p>
      </div>

      <ScrollArea className="flex-1 px-6 py-5">
        <form onSubmit={handleCreate} className="flex gap-2 mb-6 max-w-3xl">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New project name…"
            className="flex-1"
          />
          <Button type="submit" disabled={!newName.trim()}>
            <Plus className="h-4 w-4" />
            Project
          </Button>
        </form>

        {isLoading && (
          <p className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading projects…
          </p>
        )}

        {!isLoading && projects.length === 0 && (
          <div className="text-center py-16 max-w-md mx-auto space-y-3">
            <p className="text-sm text-muted-foreground">
              No projects yet. Create one above to start adding editable tests and running suites.
            </p>
          </div>
        )}

        <div className="space-y-4 max-w-3xl">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              expanded={expandedId === project.id}
              onToggleExpand={() =>
                setExpandedId((id) => (id === project.id ? null : project.id))
              }
              suite={suite}
              singleRunningId={runningId}
              onRunTask={(task) => void handleRunTask(project, task)}
              onEditTask={(task) => openEditTask(project, task)}
              onAddTask={() => openAddTask(project)}
              onDeleteTask={(taskId) =>
                void removeTaskFromProject({ projectId: project.id, taskId })
              }
              onUpdateProject={updateProject}
              onDeleteProject={() => void deleteProject(project.id)}
            />
          ))}
        </div>
      </ScrollArea>

      {editorProjectId && (
        <TestEditorDialog
          open={editorOpen}
          onOpenChange={setEditorOpen}
          projectId={editorProjectId}
          task={
            editorMode === 'edit'
              ? (editorProject?.tasks.find((t) => t.id === editorTask?.id) ?? editorTask)
              : null
          }
          mode={editorMode}
          onSaveTask={handleSaveTask}
        />
      )}
    </div>
  )
}
