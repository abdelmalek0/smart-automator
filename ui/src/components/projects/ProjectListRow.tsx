import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, FolderOpen, Loader2, MoreHorizontal, PenLine, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
import {
  getProjectCardStats,
  PROJECT_ACCENT_CLASSES,
  projectAccentIndex,
  projectListMeta,
} from '@/lib/project-view'
import { downloadProjectPack } from '@/lib/project-pack'
import type { Project } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  project: Project
  suiteActive?: boolean
  suiteBusy?: boolean
  onUpdateProject: (payload: {
    projectId: string
    name?: string
    description?: string
    url?: string
    context_prompt?: string
  }) => Promise<unknown>
  onDeleteProject: () => Promise<unknown> | void
  deleting?: boolean
}

export default function ProjectListRow({
  project,
  suiteActive = false,
  suiteBusy = false,
  onUpdateProject,
  onDeleteProject,
  deleting = false,
}: Props) {
  const navigate = useNavigate()
  const stats = getProjectCardStats(project)
  const accent = PROJECT_ACCENT_CLASSES[projectAccentIndex(project.id || project.name)]
  const description = project.description?.trim() ?? ''
  const [renaming, setRenaming] = useState(false)
  const [nameDraft, setNameDraft] = useState(project.name)
  const [savingName, setSavingName] = useState(false)

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

  function openProject() {
    if (!renaming) navigate(`/projects/${project.id}`)
  }

  return (
    <div
      role="row"
      className={cn(
        'group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl px-2 py-3.5 sm:px-3',
        'transition-colors duration-150 cursor-pointer',
        'hover:bg-accent/40 focus-within:bg-accent/40',
        suiteActive && 'bg-primary/[0.06]',
      )}
      onClick={openProject}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          openProject()
        }
      }}
      tabIndex={0}
      aria-label={`Open project ${project.name}`}
    >
      <div className="flex min-w-0 items-center gap-3" role="cell">
        <div
          className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-xs font-semibold tracking-wide',
            accent,
          )}
          aria-hidden
        >
          {stats.initials.slice(0, 1)}
        </div>

        <div className="min-w-0 flex-1">
          {renaming ? (
            <form
              className="flex max-w-md gap-2 items-center"
              onClick={(e) => e.stopPropagation()}
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
                aria-label="Project name"
                onBlur={() => void saveRename()}
                disabled={savingName}
              />
              <Button type="submit" size="sm" disabled={savingName || !nameDraft.trim()}>
                {savingName ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save'}
              </Button>
            </form>
          ) : (
            <div className="min-w-0 space-y-0.5">
              <p className="truncate text-[15px] font-medium text-foreground leading-snug">
                {project.name}
              </p>
              {description ? (
                <p className="text-sm text-muted-foreground line-clamp-2 leading-snug">
                  {description}
                </p>
              ) : (
                <p className="sm:hidden text-xs text-muted-foreground truncate">
                  {suiteBusy
                    ? 'Suite running'
                    : suiteActive
                      ? 'Suite results ready'
                      : projectListMeta(project)}
                </p>
              )}
              {(suiteBusy || suiteActive) && (
                <p className="text-xs text-primary">
                  {suiteBusy ? 'Suite running' : 'Suite results ready'}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      <div
        className="flex items-center gap-2 justify-end text-sm text-muted-foreground self-center"
        role="cell"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="hidden sm:inline tabular-nums whitespace-nowrap pr-1">
          {projectListMeta(project)}
        </span>

        <AlertDialog>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  'h-8 w-8 text-muted-foreground',
                  'sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100',
                  'data-[state=open]:opacity-100',
                )}
                aria-label={`Actions for ${project.name}`}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => navigate(`/projects/${project.id}`)}>
                <FolderOpen className="h-4 w-4" />
                Open
              </DropdownMenuItem>
              <DropdownMenuItem onClick={startRename}>
                <PenLine className="h-4 w-4" />
                Rename
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => downloadProjectPack(project)}>
                <Download className="h-4 w-4" />
                Export
              </DropdownMenuItem>
              <AlertDialogTrigger asChild>
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={(e) => e.preventDefault()}
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
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
              <AlertDialogAction onClick={() => void onDeleteProject()} disabled={deleting}>
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
