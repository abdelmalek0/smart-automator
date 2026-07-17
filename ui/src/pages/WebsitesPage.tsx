import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Globe,
  Loader2,
  MoreHorizontal,
  Play,
  Plus,
  Trash2,
} from 'lucide-react'
import type { Website, WebsiteTask } from '@/types'
import { useWebsites } from '@/hooks/useWebsites'
import { startRun } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
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
import { cn } from '@/lib/utils'

export default function WebsitesPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const {
    websites,
    isLoading,
    createWebsite,
    updateWebsite,
    deleteWebsite,
    removeTaskFromWebsite,
  } = useWebsites()

  const [newName, setNewName] = useState('')
  const [runningId, setRunningId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingContextId, setEditingContextId] = useState<string | null>(null)
  const [urlDraft, setUrlDraft] = useState('')
  const [contextDraft, setContextDraft] = useState('')

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    const website = await createWebsite({ name: newName.trim() })
    setNewName('')
    setExpandedId(website.id)
  }

  async function handleRunTask(website: Website, task: WebsiteTask) {
    setRunningId(task.id)
    try {
      const run = await startRun({
        name: task.name ?? undefined,
        task: task.task,
        success_criteria: task.success_criteria,
        headless: task.headless,
        max_steps: task.max_steps,
        cdp_url: task.cdp_url,
        fresh_profile: task.fresh_profile ?? false,
        website_id: website.id,
      })
      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      navigate(`/runs/${run.run_id}`)
    } finally {
      setRunningId(null)
    }
  }

  function startEditContext(website: Website) {
    setEditingContextId(website.id)
    setUrlDraft(website.url ?? '')
    setContextDraft(website.context_prompt)
    setExpandedId(website.id)
  }

  async function saveContext(websiteId: string) {
    await updateWebsite({
      websiteId,
      url: urlDraft.trim(),
      context_prompt: contextDraft,
    })
    setEditingContextId(null)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 px-6 pt-6 pb-4 border-b border-border">
        <div className="flex items-center gap-2 mb-1">
          <Globe className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Websites</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Group tests by website. Set the URL and shared notes (credentials, environment) — the agent
          receives them in every test run for that site.
        </p>
      </div>

      <ScrollArea className="flex-1 px-6 py-5">
        <form onSubmit={handleCreate} className="flex gap-2 mb-6 max-w-3xl">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New website name…"
            className="flex-1"
          />
          <Button type="submit" disabled={!newName.trim()}>
            <Plus className="h-4 w-4" />
            Website
          </Button>
        </form>

        {isLoading && (
          <p className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading websites…
          </p>
        )}

        {!isLoading && websites.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-16 max-w-md mx-auto">
            No websites yet. Create one above or attach a website when starting a new run.
          </p>
        )}

        <div className="space-y-4 max-w-3xl">
          {websites.map((website) => {
            const expanded = expandedId === website.id
            return (
              <Card key={website.id}>
                <CardHeader className="py-3 px-4">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setExpandedId(expanded ? null : website.id)}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      {expanded ? (
                        <ChevronDown className="h-4 w-4" />
                      ) : (
                        <ChevronRight className="h-4 w-4" />
                      )}
                    </button>
                    <div className="flex-1 min-w-0">
                      <CardTitle className="text-sm">{website.name}</CardTitle>
                      <CardDescription className="text-xs truncate">
                        {website.tasks.length} test{website.tasks.length !== 1 ? 's' : ''}
                        {website.url && (
                          <span className="mono ml-1">· {website.url}</span>
                        )}
                        {!website.url && website.context_prompt && ' · notes configured'}
                      </CardDescription>
                    </div>
                    <AlertDialog>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-8 w-8">
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => startEditContext(website)}>
                            Edit context
                          </DropdownMenuItem>
                          <AlertDialogTrigger asChild>
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
                              onSelect={(e) => e.preventDefault()}
                            >
                              <Trash2 className="h-4 w-4" />
                              Delete website
                            </DropdownMenuItem>
                          </AlertDialogTrigger>
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Delete &quot;{website.name}&quot;?</AlertDialogTitle>
                          <AlertDialogDescription>
                            This removes the website, its context prompt, and all saved tests.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction onClick={() => deleteWebsite(website.id)}>
                            Delete
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </CardHeader>

                {expanded && (
                  <CardContent className="px-4 pb-4 pt-0 space-y-4">
                    <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-3">
                      <Label className="text-xs text-muted-foreground uppercase tracking-wide">
                        Website configuration
                      </Label>
                      {editingContextId === website.id ? (
                        <>
                          <div className="space-y-1.5">
                            <Label htmlFor={`url-${website.id}`} className="text-xs">
                              URL
                            </Label>
                            <Input
                              id={`url-${website.id}`}
                              value={urlDraft}
                              onChange={(e) => setUrlDraft(e.target.value)}
                              placeholder="https://app.example.com"
                              className="mono text-sm"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <Label htmlFor={`notes-${website.id}`} className="text-xs">
                              Site notes
                            </Label>
                            <Textarea
                              id={`notes-${website.id}`}
                              value={contextDraft}
                              onChange={(e) => setContextDraft(e.target.value)}
                              placeholder="Login: admin@example.com / password123&#10;Default store: Downtown&#10;Test card: 4242..."
                              rows={4}
                              className="text-sm"
                            />
                          </div>
                          <div className="flex gap-2">
                            <Button size="sm" onClick={() => saveContext(website.id)}>
                              Save
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setEditingContextId(null)}
                            >
                              Cancel
                            </Button>
                          </div>
                        </>
                      ) : (
                        <>
                          {website.url ? (
                            <p className="text-xs mono text-primary break-all">{website.url}</p>
                          ) : (
                            <p className="text-xs text-muted-foreground italic">No URL set</p>
                          )}
                          {website.context_prompt ? (
                            <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-sans leading-relaxed">
                              {website.context_prompt}
                            </pre>
                          ) : (
                            <p className="text-xs text-muted-foreground italic">
                              No site notes yet.
                            </p>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => startEditContext(website)}
                          >
                            {website.url || website.context_prompt ? 'Edit configuration' : 'Add configuration'}
                          </Button>
                        </>
                      )}
                    </div>

                    {website.tasks.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic px-1">
                        No tests yet — save a run to this website from <em>New Run</em>.
                      </p>
                    ) : (
                      <ul className="divide-y divide-border rounded-lg border border-border">
                        {website.tasks.map((task) => (
                          <li
                            key={task.id}
                            className={cn(
                              'flex items-start gap-3 px-4 py-3 group hover:bg-accent/20 transition-colors',
                            )}
                          >
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium leading-snug line-clamp-1">
                                {task.name || 'Untitled test'}
                              </p>
                              <p className="text-sm leading-snug line-clamp-2 text-muted-foreground mt-0.5">
                                {task.task}
                              </p>
                              {task.success_criteria && (
                                <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
                                  Criteria: {task.success_criteria}
                                </p>
                              )}
                              <CardDescription className="flex gap-3 mt-1 text-[10px]">
                                <span className="mono">{task.max_steps} steps</span>
                                {task.headless && <span>headless</span>}
                              </CardDescription>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <Button
                                size="sm"
                                onClick={() => handleRunTask(website, task)}
                                disabled={runningId === task.id}
                              >
                                {runningId === task.id ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Play className="h-3.5 w-3.5" />
                                )}
                                Run
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
                                onClick={() =>
                                  removeTaskFromWebsite({
                                    websiteId: website.id,
                                    taskId: task.id,
                                  })
                                }
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                )}
              </Card>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  )
}
