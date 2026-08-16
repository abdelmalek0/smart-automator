import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Globe, Loader2, Play } from 'lucide-react'
import { getConfig, getRun, listProjects, startRun } from '@/api'
import ConnectOfflineNotice from '@/components/ConnectOfflineNotice'
import { useProjects } from '@/hooks/useProjects'
import { useRunStartGate } from '@/hooks/useRunStartGate'
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
import { canRunUseAutomatic } from '@/lib/run-status'
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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveToProject, setSaveToProject] = useState(
    () => Boolean(initialValues?.website_id) && !initialValues?.website_task_id,
  )
  const [useReplayScript, setUseReplayScript] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const { projects, addTaskToProject } = useProjects()
  const runStartGate = useRunStartGate()
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: getConfig })
  const { data: projectList = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
  })

  const isRerun = Boolean(initialValues)
  const sourceRunId = initialValues?.source_run_id
  const { data: sourceRun, isFetched: sourceRunFetched, isError: sourceRunMissing } = useQuery({
    queryKey: ['runs', sourceRunId],
    queryFn: () => getRun(sourceRunId!),
    enabled: Boolean(sourceRunId),
    retry: false,
  })
  // Training is always available (new independent training).
  const canUseTraining = true
  // Automatic only when a replay source is available (live training or retained orphan replay).
  const canUseAutomatic = Boolean(
    sourceRunId &&
      ((sourceRun && canRunUseAutomatic(sourceRun)) ||
        (sourceRunMissing && Boolean(initialValues?.use_replay_script))),
  )
  const selectedProject =
    projectId !== NO_PROJECT ? projectList.find((p) => p.id === projectId) : null
  const hasTopProject = projectId !== NO_PROJECT
  const alreadyLinkedToTask = Boolean(initialValues?.website_task_id)
  const saveToggleDisabled = !hasTopProject || alreadyLinkedToTask

  useEffect(() => {
    if (alreadyLinkedToTask) return
    if (hasTopProject) {
      setSaveToProject(true)
    } else {
      setSaveToProject(false)
    }
  }, [projectId, hasTopProject, alreadyLinkedToTask])

  useEffect(() => {
    if (!config || initialValues) return
    setFreshProfile(config.fresh_profile ?? true)
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
    const wantsAutomatic = Boolean(initialValues.use_replay_script)
    if (wantsAutomatic && sourceRunId && !sourceRunFetched && !sourceRunMissing) return
    if (wantsAutomatic && canUseAutomatic) {
      setUseReplayScript(true)
    } else if (!canUseAutomatic) {
      setUseReplayScript(false)
    } else {
      setUseReplayScript(false)
    }
  }, [initialValues, sourceRun, sourceRunId, sourceRunFetched, sourceRunMissing, canUseAutomatic])

  useEffect(() => {
    if (!canUseAutomatic && useReplayScript) {
      setUseReplayScript(false)
    }
  }, [canUseAutomatic, useReplayScript])

  useEffect(() => {
    if (!canUseTraining && !useReplayScript) {
      setUseReplayScript(true)
    }
  }, [canUseTraining, useReplayScript])


  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!task.trim() || !successCriteria.trim() || !runStartGate.canStartRun) return
    setLoading(true)
    setError(null)
    try {
      let runProjectId = projectId !== NO_PROJECT ? projectId : undefined
      let websiteTaskId = initialValues?.website_task_id

      const useAutomatic = Boolean(canUseAutomatic && useReplayScript && sourceRunId)

      const payload = {
        name: name.trim() || undefined,
        task: task.trim(),
        success_criteria: successCriteria.trim(),
        headless,
        max_steps: maxSteps,
        cdp_url: undefined,
        fresh_profile: freshProfile,
        website_id: runProjectId,
        ...(websiteTaskId ? { website_task_id: websiteTaskId } : {}),
        ...(useAutomatic
          ? {
              source_run_id: sourceRunId,
              use_replay_script: true,
            }
          : { use_replay_script: false }),
      }

      if (saveToProject && runProjectId) {
        const createdTask = await addTaskToProject({
          projectId: runProjectId,
          name: payload.name,
          task: payload.task,
          success_criteria: payload.success_criteria,
          headless: payload.headless,
          max_steps: payload.max_steps,
          cdp_url: payload.cdp_url,
          fresh_profile: payload.fresh_profile ?? true,
        })
        websiteTaskId = createdTask.id
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
          <DialogTitle>
            {isRerun ? 'Re-run QA Test' : 'New QA Run'}
          </DialogTitle>
          <DialogDescription>
            What should the agent do, and how do you know it passed?
          </DialogDescription>
          {isRerun && useReplayScript && sourceRunId && (
            <p className="pt-1 text-xs text-muted-foreground">
              From training{' '}
              {sourceRun ? (
                <Link
                  to={`/runs/${sourceRunId}`}
                  className="mono text-primary hover:underline underline-offset-2"
                  onClick={onClose}
                >
                  {sourceRunId.slice(0, 8)}
                </Link>
              ) : (
                <span className="mono">{sourceRunId.slice(0, 8)}</span>
              )}
              {!sourceRun ? ' (removed from list — replay kept)' : null}
            </p>
          )}
          {isRerun && !useReplayScript && (
            <p className="pt-1 text-xs text-muted-foreground">
              Starts a new training run. Training runs are not linked to other trainings.
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
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/80 bg-muted/20 px-3 py-2.5">
                <div className="space-y-0.5">
                  <Label
                    htmlFor="save-project"
                    className={cn('font-normal', saveToggleDisabled && 'text-muted-foreground')}
                  >
                    Save test to project
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    {alreadyLinkedToTask
                      ? 'This run is already linked to a saved test.'
                      : hasTopProject
                        ? `Adds this run as a test in ${selectedProject?.name ?? 'the selected project'}.`
                        : 'Choose a project above to save this test.'}
                  </p>
                </div>
                <Switch
                  id="save-project"
                  checked={saveToProject}
                  onCheckedChange={setSaveToProject}
                  disabled={saveToggleDisabled}
                />
              </div>
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
                What should be true when done. Present: visible on the final page.
                Referential: a value now should match one seen earlier (it is recorded from the page automatically).
              </p>
              <Textarea
                id="success-criteria"
                value={successCriteria}
                onChange={(e) => setSuccessCriteria(e.target.value)}
                placeholder="e.g. Order confirmation shows a total. Or: checkout total matches the amount shown when the item was added."
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
                  onClick={() => canUseTraining && setUseReplayScript(false)}
                  disabled={!canUseTraining}
                  title={
                    canUseTraining
                      ? undefined
                      : 'Training is not available for this run'
                  }
                  className={cn(
                    'rounded-md px-3 py-2 text-sm transition-colors',
                    !useReplayScript
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground',
                    !canUseTraining && 'cursor-not-allowed opacity-50',
                  )}
                >
                  Training
                </button>
                <button
                  type="button"
                  onClick={() => canUseAutomatic && setUseReplayScript(true)}
                  disabled={!canUseAutomatic}
                  title={
                    canUseAutomatic
                      ? undefined
                      : 'Automatic needs a saved replay from a passed training run'
                  }
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
                  ? 'Runs the saved Playwright steps from the training run, then checks criteria.'
                  : canUseAutomatic
                    ? 'New training with LLM and element highlights. Not linked to other training runs.'
                    : 'Automatic is unavailable until a training run passes and saves a replay.'}
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
                        onCheckedChange={setFreshProfile}
                      />
                      <Label htmlFor="fresh" className="font-normal">
                        Fresh profile
                      </Label>
                    </div>
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
                </div>
              )}
            </div>

            {runStartGate.blockReason === 'offline' && (
              <ConnectOfflineNotice message={runStartGate.blockHint ?? undefined} />
            )}

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
            <Button
              type="submit"
              disabled={
                loading ||
                !task.trim() ||
                !successCriteria.trim() ||
                !runStartGate.canStartRun
              }
              title={
                runStartGate.blockReason === 'busy'
                  ? (runStartGate.blockHint ?? undefined)
                  : undefined
              }
            >
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
