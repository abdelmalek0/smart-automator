import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Globe, Loader2, Play } from 'lucide-react'
import { getConfig, getRun, listProjects, startRun } from '@/api'
import { useProjects } from '@/hooks/useProjects'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { RunDraft } from '@/types'

const NO_PROJECT = '__none__'

interface Props {
  onClose: () => void
  redirectOnStart?: boolean
  initialValues?: RunDraft
}

export default function NewRunModal({
  onClose,
  redirectOnStart = true,
  initialValues,
}: Props) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [name, setName] = useState(initialValues?.name ?? '')
  const [task, setTask] = useState(initialValues?.task ?? '')
  const [successCriteria, setSuccessCriteria] = useState(initialValues?.success_criteria ?? '')
  const [projectId, setProjectId] = useState<string>(initialValues?.website_id ?? NO_PROJECT)
  const [headless, setHeadless] = useState(initialValues?.headless ?? false)
  const [freshProfile, setFreshProfile] = useState(initialValues?.fresh_profile ?? true)
  const [maxSteps, setMaxSteps] = useState(initialValues?.max_steps ?? 100)
  const [cdpUrl, setCdpUrl] = useState(initialValues?.cdp_url ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveToProject, setSaveToProject] = useState(false)
  const [useReplayScript, setUseReplayScript] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [projectMode, setProjectMode] = useState<'new' | 'existing'>('existing')
  const [newProjectName, setNewProjectName] = useState('')
  const [saveProjectId, setSaveProjectId] = useState('')
  const { projects, createProject, addTaskToProject } = useProjects()
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: getConfig })
  const { data: projectList = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
  })

  const isRerun = Boolean(initialValues?.source_run_id)
  const sourceRunId = initialValues?.source_run_id
  const { data: sourceRun } = useQuery({
    queryKey: ['runs', sourceRunId],
    queryFn: () => getRun(sourceRunId!),
    enabled: Boolean(sourceRunId),
  })
  const canUseAutomatic = Boolean(sourceRunId && sourceRun?.has_replay_script)
  const selectedProject =
    projectId !== NO_PROJECT ? projectList.find((p) => p.id === projectId) : null

  useEffect(() => {
    if (!config || initialValues) return
    setFreshProfile(config.fresh_profile ?? true)
    const globalCdp = config.cdp_url ?? ''
    setCdpUrl(globalCdp)
    if (globalCdp.trim()) setAdvancedOpen(true)
  }, [config, initialValues])

  useEffect(() => {
    if (!initialValues) return
    setName(initialValues.name ?? '')
    setTask(initialValues.task)
    setSuccessCriteria(initialValues.success_criteria)
    setProjectId(initialValues.website_id ?? NO_PROJECT)
    setHeadless(initialValues.headless ?? false)
    setFreshProfile(initialValues.fresh_profile ?? true)
    setMaxSteps(initialValues.max_steps ?? 100)
    setCdpUrl(initialValues.cdp_url ?? '')
    const wantsAutomatic =
      initialValues.use_replay_script ?? Boolean(initialValues.source_run_id)
    if (initialValues.source_run_id && sourceRun === undefined) return
    setUseReplayScript(wantsAutomatic && Boolean(sourceRun?.has_replay_script))
  }, [initialValues, sourceRun])

  useEffect(() => {
    if (!canUseAutomatic && useReplayScript) {
      setUseReplayScript(false)
    }
  }, [canUseAutomatic, useReplayScript])

  const cdpActive = Boolean(cdpUrl.trim())

  useEffect(() => {
    if (cdpActive && freshProfile) {
      setFreshProfile(false)
    }
  }, [cdpActive, freshProfile])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!task.trim() || !successCriteria.trim()) return
    setLoading(true)
    setError(null)
    try {
      let runProjectId = projectId !== NO_PROJECT ? projectId : undefined
      let websiteTaskId = initialValues?.website_task_id

      const useAutomatic = canUseAutomatic && useReplayScript

      const payload = {
        name: name.trim() || undefined,
        task: task.trim(),
        success_criteria: successCriteria.trim(),
        headless,
        max_steps: maxSteps,
        cdp_url: cdpUrl.trim() || undefined,
        fresh_profile: cdpActive ? false : freshProfile,
        website_id: runProjectId,
        ...(websiteTaskId ? { website_task_id: websiteTaskId } : {}),
        ...(sourceRunId
          ? {
              source_run_id: sourceRunId,
              use_replay_script: useAutomatic,
            }
          : { use_replay_script: false }),
      }

      if (saveToProject) {
        let targetProjectId = saveProjectId
        if (projectMode === 'new' && newProjectName.trim()) {
          const project = await createProject({ name: newProjectName.trim() })
          targetProjectId = project.id
          runProjectId = runProjectId ?? project.id
        }
        if (targetProjectId) {
          const createdTask = await addTaskToProject({
            projectId: targetProjectId,
            name: payload.name,
            task: payload.task,
            success_criteria: payload.success_criteria,
            headless: payload.headless,
            max_steps: payload.max_steps,
            cdp_url: payload.cdp_url,
            fresh_profile: payload.fresh_profile ?? true,
          })
          websiteTaskId = createdTask.id
          if (!runProjectId) runProjectId = targetProjectId
        }
      }

      const run = await startRun({
        ...payload,
        website_id: runProjectId,
        ...(websiteTaskId ? { website_task_id: websiteTaskId } : {}),
      })
      await queryClient.invalidateQueries({ queryKey: ['runs'] })
      onClose()
      if (redirectOnStart) {
        navigate(`/runs/${run.run_id}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start run')
      setLoading(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl max-h-[90vh] flex flex-col gap-0 p-0 overflow-hidden">
        <DialogHeader className="flex-shrink-0 px-6 pt-6 pb-4 border-b border-border">
          <DialogTitle>{isRerun ? 'Re-run QA Test' : 'New QA Run'}</DialogTitle>
          <DialogDescription>
            What should the agent do, and how do you know it passed?
          </DialogDescription>
          {isRerun && initialValues?.source_run_id && (
            <p className="pt-1 text-xs text-muted-foreground">
              From{' '}
              <Link
                to={`/runs/${initialValues.source_run_id}`}
                className="mono text-primary hover:underline underline-offset-2"
                onClick={onClose}
              >
                {initialValues.source_run_id.slice(0, 8)}
              </Link>
            </p>
          )}
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col flex-1 min-h-0">
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            <div className="space-y-2">
              <Label htmlFor="project">
                Project <span className="text-muted-foreground font-normal">(optional)</span>
              </Label>
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger id="project">
                  <SelectValue placeholder="No project — run standalone" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_PROJECT}>No project</SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedProject && (selectedProject.url || selectedProject.context_prompt) && (
                <div className="text-xs text-muted-foreground border border-border rounded-md p-3 space-y-1 bg-muted/30">
                  <p className="flex items-center gap-1 text-foreground font-medium">
                    <Globe className="h-3 w-3 text-primary" />
                    {selectedProject.name} — passed to the agent
                  </p>
                  {selectedProject.url && (
                    <p className="mono text-primary break-all">{selectedProject.url}</p>
                  )}
                  {selectedProject.context_prompt && (
                    <p className="whitespace-pre-wrap leading-relaxed line-clamp-4">
                      {selectedProject.context_prompt}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="name">
                Test name <span className="text-muted-foreground font-normal">(optional)</span>
              </Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Checkout smoke test"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task">Test task</Label>
              <p className="text-xs text-muted-foreground">What the agent should do.</p>
              <Textarea
                id="task"
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="e.g. Add an item to cart and proceed to checkout."
                rows={3}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="success-criteria">Success criteria</Label>
              <p className="text-xs text-muted-foreground">
                What should be true on the page when done (observations, not steps).
              </p>
              <Textarea
                id="success-criteria"
                value={successCriteria}
                onChange={(e) => setSuccessCriteria(e.target.value)}
                placeholder="e.g. Order confirmation page shows with order total visible."
                rows={3}
                required
              />
            </div>

            <div className="space-y-2">
              <Label>Run mode</Label>
              <div
                className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-muted/40 p-1"
                role="group"
                aria-label="Run mode"
              >
                <button
                  type="button"
                  onClick={() => setUseReplayScript(false)}
                  className={cn(
                    'rounded-md px-3 py-2 text-sm transition-colors',
                    !useReplayScript
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  Training
                </button>
                <button
                  type="button"
                  onClick={() => canUseAutomatic && setUseReplayScript(true)}
                  disabled={!canUseAutomatic}
                  className={cn(
                    'rounded-md px-3 py-2 text-sm transition-colors',
                    useReplayScript
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground',
                    !canUseAutomatic && 'cursor-not-allowed opacity-50',
                  )}
                >
                  Automatic execution
                </button>
              </div>
              <p className="text-xs text-muted-foreground">
                {useReplayScript
                  ? 'Runs the saved Playwright steps, then checks criteria.'
                  : canUseAutomatic
                    ? 'Training run with LLM and element highlights.'
                    : 'Train this flow first, then re-run to use automatic execution.'}
              </p>
            </div>

            <div className="border border-border rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={() => setAdvancedOpen((open) => !open)}
                className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-sm text-left hover:bg-muted/40 transition-colors"
                aria-expanded={advancedOpen}
              >
                <span className="font-medium">Advanced</span>
                <ChevronDown
                  className={cn(
                    'h-4 w-4 text-muted-foreground transition-transform',
                    advancedOpen && 'rotate-180',
                  )}
                />
              </button>
              {advancedOpen && (
                <div className="space-y-4 border-t border-border px-3 py-4">
                  <div className="flex flex-wrap gap-x-6 gap-y-3">
                    <div className="flex items-center gap-2">
                      <Switch id="headless" checked={headless} onCheckedChange={setHeadless} />
                      <Label htmlFor="headless" className="font-normal">
                        Headless
                      </Label>
                    </div>
                    <div className="flex items-center gap-2">
                      <Switch
                        id="fresh"
                        checked={freshProfile}
                        disabled={cdpActive}
                        onCheckedChange={setFreshProfile}
                      />
                      <Label htmlFor="fresh" className="font-normal">
                        Isolated profile
                      </Label>
                    </div>
                    {cdpActive && (
                      <p className="text-xs text-muted-foreground w-full -mt-2">
                        Not used while CDP URL is set — profile is controlled by Smart Automator
                        Connect.
                      </p>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">
                      Max steps: <span className="mono text-primary">{maxSteps}</span>
                    </Label>
                    <input
                      type="range"
                      min={10}
                      max={200}
                      step={10}
                      value={maxSteps}
                      onChange={(e) => setMaxSteps(Number(e.target.value))}
                      className="w-full accent-primary"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="cdp">
                      CDP URL{' '}
                      <span className="text-muted-foreground font-normal">(optional)</span>
                    </Label>
                    <Input
                      id="cdp"
                      value={cdpUrl}
                      onChange={(e) => setCdpUrl(e.target.value)}
                      placeholder="ws://localhost:9222/devtools/browser/..."
                      className="mono text-sm"
                    />
                    <p className="text-xs text-muted-foreground">
                      Uses the connected browser&apos;s profile (set in Connect).
                    </p>
                  </div>

                  <div className="space-y-3 pt-1 border-t border-border">
                    <div className="flex items-center gap-2">
                      <Switch
                        id="save-project"
                        checked={saveToProject}
                        onCheckedChange={setSaveToProject}
                      />
                      <Label htmlFor="save-project" className="font-normal">
                        Save test to project
                      </Label>
                    </div>
                    {saveToProject && (
                      <div className="space-y-2">
                        <div className="flex gap-4">
                          <label className="flex items-center gap-1.5 cursor-pointer text-sm">
                            <input
                              type="radio"
                              checked={projectMode === 'new'}
                              onChange={() => setProjectMode('new')}
                              className="accent-primary"
                            />
                            New project
                          </label>
                          <label
                            className={`flex items-center gap-1.5 text-sm ${
                              projects.length === 0
                                ? 'opacity-40 cursor-not-allowed'
                                : 'cursor-pointer'
                            }`}
                          >
                            <input
                              type="radio"
                              checked={projectMode === 'existing'}
                              onChange={() => setProjectMode('existing')}
                              disabled={projects.length === 0}
                              className="accent-primary"
                            />
                            Existing project
                          </label>
                        </div>
                        {projectMode === 'new' ? (
                          <Input
                            value={newProjectName}
                            onChange={(e) => setNewProjectName(e.target.value)}
                            placeholder="Project name…"
                          />
                        ) : (
                          <Select value={saveProjectId} onValueChange={setSaveProjectId}>
                            <SelectTrigger>
                              <SelectValue placeholder="Select a project…" />
                            </SelectTrigger>
                            <SelectContent>
                              {projects.map((p) => (
                                <SelectItem key={p.id} value={p.id}>
                                  {p.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {error && (
              <p className="text-destructive text-sm bg-destructive/10 border border-destructive/30 rounded-md px-3 py-2">
                {error}
              </p>
            )}
          </div>

          <DialogFooter className="flex-shrink-0 px-6 py-4 border-t border-border sm:justify-end">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading || !task.trim() || !successCriteria.trim()}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Starting…
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  {isRerun ? 'Re-run' : 'Run'}
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
