import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderKanban, Loader2, Plus, Search, Upload } from 'lucide-react'
import CreateProjectDialog from '@/components/projects/CreateProjectDialog'
import ProjectListRow from '@/components/projects/ProjectListRow'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useProjectSuiteRunner } from '@/hooks/useProjectSuiteRunner'
import { useProjects } from '@/hooks/useProjects'
import {
  filterAndSortProjects,
  type ProjectFilter,
} from '@/lib/project-view'
import { parseProjectPack } from '@/lib/project-pack'
import { cn } from '@/lib/utils'

const FILTERS: { id: ProjectFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'with-tests', label: 'With tests' },
  { id: 'trained', label: 'Trained' },
]

export default function ProjectsPage() {
  const navigate = useNavigate()
  const {
    projects,
    isLoading,
    error,
    createProject,
    updateProject,
    deleteProject,
    importProject,
    isCreating,
    isDeleting,
    isImportingProject,
  } = useProjects()
  const suite = useProjectSuiteRunner()

  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ProjectFilter>('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const importFileRef = useRef<HTMLInputElement>(null)

  async function handleImportFile(file: File) {
    setImportError(null)
    try {
      const text = await file.text()
      let parsed: unknown
      try {
        parsed = JSON.parse(text)
      } catch {
        throw new Error('Invalid project file')
      }
      const pack = parseProjectPack(parsed)
      const project = await importProject(pack)
      navigate(`/projects/${project.id}`)
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Could not import project')
    } finally {
      if (importFileRef.current) {
        importFileRef.current.value = ''
      }
    }
  }

  function openImport() {
    setImportError(null)
    importFileRef.current?.click()
  }

  const visible = useMemo(
    () => filterAndSortProjects(projects, query, 'name-asc', filter),
    [projects, query, filter],
  )

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <input
        ref={importFileRef}
        type="file"
        accept="application/json,.json"
        className="sr-only"
        aria-label="Import project JSON"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) {
            void handleImportFile(file)
          }
        }}
      />
      <ScrollArea className="flex-1">
        <div className="mx-auto w-full max-w-3xl px-4 sm:px-8 pt-10 pb-16">
          {/* Header: title + search + new */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-8">
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">Projects</h1>
            <div className="flex items-center gap-2 w-full sm:w-auto">
              <div className="relative flex-1 sm:w-56">
                <Search
                  className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground pointer-events-none"
                  aria-hidden
                />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search projects"
                  aria-label="Search projects"
                  className="h-9 rounded-full border-border/60 bg-muted/40 pl-9 pr-3 text-sm shadow-none focus-visible:ring-1"
                />
              </div>
              <Button
                variant="outline"
                size="sm"
                className="h-9 rounded-full px-4 shrink-0"
                disabled={isImportingProject}
                onClick={openImport}
              >
                {isImportingProject ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
                Import
              </Button>
              <Button
                onClick={() => setCreateOpen(true)}
                size="sm"
                className="h-9 rounded-full px-4 shrink-0"
              >
                <Plus className="h-4 w-4" />
                New
              </Button>
            </div>
          </div>

          {importError && (
            <div
              role="alert"
              className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive mb-4"
            >
              {importError}
            </div>
          )}

          {/* Filter pills */}
          {!isLoading && projects.length > 0 && (
            <div
              className="flex flex-wrap items-center gap-1.5 mb-6"
              role="tablist"
              aria-label="Filter projects"
            >
              {FILTERS.map((tab) => {
                const active = filter === tab.id
                return (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setFilter(tab.id)}
                    className={cn(
                      'rounded-full px-3.5 py-1.5 text-sm transition-colors',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      active
                        ? 'bg-accent text-foreground font-medium'
                        : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                    )}
                  >
                    {tab.label}
                  </button>
                )
              })}
            </div>
          )}

          {isLoading && (
            <p className="text-sm text-muted-foreground flex items-center gap-2 py-16 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading projects…
            </p>
          )}

          {error && (
            <div
              role="alert"
              className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive mb-4"
            >
              {error instanceof Error ? error.message : 'Failed to load projects'}
            </div>
          )}

          {!isLoading && projects.length === 0 && (
            <div className="py-20 text-center space-y-4 animate-in fade-in-0 duration-300">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
                <FolderKanban className="h-6 w-6" aria-hidden />
              </div>
              <div className="space-y-1.5">
                <h2 className="text-base font-medium">No projects yet</h2>
                <p className="text-sm text-muted-foreground max-w-sm mx-auto">
                  Create a project to group tests and run them as a suite.
                </p>
              </div>
              <Button onClick={() => setCreateOpen(true)} className="rounded-full">
                <Plus className="h-4 w-4" />
                New project
              </Button>
              <Button
                variant="outline"
                onClick={openImport}
                disabled={isImportingProject}
                className="rounded-full"
              >
                {isImportingProject ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
                Import
              </Button>
            </div>
          )}

          {!isLoading && projects.length > 0 && visible.length === 0 && (
            <div className="py-16 text-center space-y-2">
              <p className="text-sm text-muted-foreground">No matching projects</p>
              <Button
                variant="ghost"
                size="sm"
                className="rounded-full"
                onClick={() => {
                  setQuery('')
                  setFilter('all')
                }}
              >
                Clear filters
              </Button>
            </div>
          )}

          {!isLoading && visible.length > 0 && (
            <div role="table" aria-label="Projects">
              <div
                role="row"
                className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-2 sm:px-3 pb-2 text-xs text-muted-foreground"
              >
                <div role="columnheader">Name</div>
                <div role="columnheader" className="text-right pr-10 hidden sm:block">
                  Tests
                </div>
              </div>

              <div role="rowgroup" className="flex flex-col">
                {visible.map((project) => (
                  <ProjectListRow
                    key={project.id}
                    project={project}
                    suiteBusy={suite.isRunning && suite.state.projectId === project.id}
                    suiteActive={
                      suite.state.phase !== 'idle' && suite.state.projectId === project.id
                    }
                    onUpdateProject={updateProject}
                    onDeleteProject={async () => {
                      await deleteProject(project.id)
                    }}
                    deleting={isDeleting}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>

      <CreateProjectDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        creating={isCreating}
        onCreate={async (payload) => {
          const project = await createProject(payload)
          navigate(`/projects/${project.id}`)
          return project
        }}
      />
    </div>
  )
}
