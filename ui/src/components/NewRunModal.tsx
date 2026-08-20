import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { rerunProjectLabel, rerunTitleLabel, runModeShowsMaxSteps } from '@/lib/new-run-modal'
import { cn } from '@/lib/utils'
import { canRunUseAutomatic, MANUAL_PLACEHOLDER_TASK } from '@/lib/run-status'
import type { RunDraft, RunMode } from '@/types'

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
  const [runMode, setRunMode] = useState<RunMode>(() => {
    if (initialValues?.run_mode) return initialValues.run_mode
    if (initialValues?.use_replay_script) return 'automatic'
    return 'training'
  })
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
  const isManual = runMode === 'manual'
  const showMaxSteps = runModeShowsMaxSteps(runMode)
  const selectedProject =
    projectId !== NO_PROJECT ? projectList.find((p) => p.id === projectId) : null
  const rerunProjectName = selectedProject?.name ?? projects.find((p) => p.id === projectId)?.name
  const rerunTitle = rerunTitleLabel(name || initialValues?.name)
  const rerunProject = rerunProjectLabel(
    projectId !== NO_PROJECT ? projectId : undefined,
    rerunProjectName,
  )
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
    setHeadless(initialValues.run_mode === 'manual' ? false : (initialValues.headless ?? false))
    setFreshProfile(initialValues.fresh_profile ?? true)
    setMaxSteps(initialValues.max_steps ?? 100)
    if (initialValues.run_mode === 'manual') {
      setRunMode('manual')
      return
    }
    const wantsAutomatic =
      initialValues.run_mode === 'automatic' || Boolean(initialValues.use_replay_script)
    if (wantsAutomatic && sourceRunId && !sourceRunFetched && !sourceRunMissing) return
    if (wantsAutomatic && canUseAutomatic) {
      setRunMode('automatic')
    } else {
      setRunMode('training')
    }
  }, [initialValues, sourceRun, sourceRunId, sourceRunFetched, sourceRunMissing, canUseAutomatic])

  useEffect(() => {
    if (!canUseAutomatic && runMode === 'automatic') {
      setRunMode('training')
    }
  }, [canUseAutomatic, runMode])


  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!successCriteria.trim() || !runStartGate.canStartRun) return
    if (!isManual && !task.trim()) return
    setLoading(true)
    setError(null)
    try {
      let runProjectId = projectId !== NO_PROJECT ? projectId : undefined
      let websiteTaskId = initialValues?.website_task_id

      const useAutomatic = Boolean(canUseAutomatic && runMode === 'automatic' && sourceRunId)
      const taskText = isManual ? '' : task.trim()
      const projectTaskText = isManual
        ? task.trim() || MANUAL_PLACEHOLDER_TASK
        : task.trim()

      const payload = {
        name: name.trim() || undefined,
        task: taskText,
        success_criteria: successCriteria.trim(),
        headless: isManual ? false : headless,
        max_steps: maxSteps,
        cdp_url: undefined,
        fresh_profile: freshProfile,
        website_id: runProjectId,
        run_mode: isManual ? 'manual' as const : useAutomatic ? 'automatic' as const : 'training' as const,
        ...(websiteTaskId ? { website_task_id: websiteTaskId } : {}),
        ...(useAutomatic
          ? {
              source_run_id: sourceRunId,
              use_replay_script: true,
            }
          : { use_replay_script: false }),
      }

      if (!isRerun && saveToProject && runProjectId) {
        const createdTask = await addTaskToProject({
          projectId: runProjectId,
          name: payload.name,
          task: projectTaskText,
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

  function runModeDescription(): string {
    if (runMode === 'automatic') {
      return 'Runs the saved Playwright steps from the source run, then checks criteria.'
    }
    if (runMode === 'manual') {
      return 'Do the steps in the browser. We will save a replay and write the test task from what you did.'
    }
    if (isRerun || canUseAutomatic) {
      return 'New training with LLM and element highlights. Not linked to other training runs.'
    }
    return 'Automatic is unavailable until a training or manual run passes and saves a replay.'
  }

  function runModeSelector() {
    return (
      <div className="space-y-2">
        <Label>Run mode</Label>
        <div
          className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-muted/40 p-1"
          role="group"
          aria-label="Run mode"
        >
          <button
            type="button"
            onClick={() => canUseTraining && setRunMode('training')}
            disabled={!canUseTraining}
            title={
              canUseTraining ? undefined : 'Training is not available for this run'
            }
            className={cn(
              'rounded-md px-3 py-2 text-sm transition-colors',
              runMode === 'training'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
              !canUseTraining && 'cursor-not-allowed opacity-50',
            )}
          >
            Training
          </button>
          <button
            type="button"
            onClick={() => {
              setRunMode('manual')
              setHeadless(false)
            }}
            className={cn(
              'rounded-md px-3 py-2 text-sm transition-colors',
              runMode === 'manual'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            Manual
          </button>
          <button
            type="button"
            onClick={() => canUseAutomatic && setRunMode('automatic')}
            disabled={!canUseAutomatic}
            title={
              canUseAutomatic
                ? undefined
                : 'Automatic needs a saved replay from a passed training or manual run'
            }
            className={cn(
              'rounded-md px-3 py-2 text-sm transition-colors',
              runMode === 'automatic'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
              !canUseAutomatic && 'cursor-not-allowed opacity-50',
            )}
          >
            Automatic
          </button>
        </div>
        <p className="text-xs text-muted-foreground">{runModeDescription()}</p>
      </div>
    )
  }

  function executionOptions({ includeMaxSteps }: { includeMaxSteps: boolean }) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            <Switch
              id="headless"
              checked={isManual ? false : headless}
              onCheckedChange={setHeadless}
              disabled={isManual}
            />
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

        {includeMaxSteps && (
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
              aria-label="Max steps"
            />
          </div>
        )}
      </div>
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className={cn(
          'max-h-[90vh] flex flex-col gap-0 p-0 overflow-hidden',
          isRerun ? 'max-w-md' : 'max-w-xl',
        )}
      >
        <DialogHeader className="flex-shrink-0 px-6 pt-6 pb-4 border-b border-border">
          <DialogTitle>
            {isRerun ? 'Re-run QA Test' : 'New QA Run'}
          </DialogTitle>
          <DialogDescription>
            {isRerun
              ? runModeDescription()
              : isManual
                ? 'Do the steps in the browser. We will save a replay and write the test task from what you did.'
                : 'What should the agent do, and how do you know it passed?'}
          </DialogDescription>
          {!isRerun && isManual && (
            <p className="pt-1 text-xs text-muted-foreground">
              Completing the demonstration marks the test trained. Success criteria are stored for Automatic later.
            </p>
          )}
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col flex-1 min-h-0">
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            {isRerun ? (
              <>
                <div className="space-y-2">
                  <Label htmlFor="rerun-project">Project</Label>
                  <Input id="rerun-project" value={rerunProject} disabled readOnly />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="rerun-title">Title</Label>
                  <Input id="rerun-title" value={rerunTitle} disabled readOnly />
                </div>

                {runModeSelector()}
                {executionOptions({ includeMaxSteps: showMaxSteps })}
              </>
            ) : (
              <>
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

                {!isManual && (
                  <div className="space-y-2">
                    <Label htmlFor="task">Test task</Label>
                    <p className="text-xs text-muted-foreground">What the agent should do.</p>
                    <Textarea
                      id="task"
                      value={task}
                      onChange={(e) => setTask(e.target.value)}
                      placeholder="e.g. Add an item to cart and proceed to checkout."
                      rows={8}
                      className="whitespace-pre-wrap"
                      required
                    />
                  </div>
                )}
                {isManual && (
                  <p className="text-xs text-muted-foreground rounded-md border border-border bg-muted/30 px-3 py-2">
                    Test task will be filled from what you do in the browser.
                  </p>
                )}

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

                {runModeSelector()}

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
                    <div className="border-t border-border px-3 py-4">
                      {executionOptions({ includeMaxSteps: showMaxSteps })}
                    </div>
                  )}
                </div>
              </>
            )}

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
                (!isManual && !task.trim()) ||
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
