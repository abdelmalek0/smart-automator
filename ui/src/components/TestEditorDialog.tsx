import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react'
import { getConfig, getRunReplay, updateRunReplay } from '@/api'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { ProjectTask, ReplayStep } from '@/types'

export const REPLAY_ACTIONS = [
  'go_to_url',
  'click_element',
  'input_text',
  'wait',
  'send_keys',
  'select_dropdown_option',
  'scroll_to_text',
  'scroll_to_percent',
  'scroll_to_top',
  'scroll_to_bottom',
  'go_back',
  'search_google',
  'open_tab',
  'switch_tab',
  'close_tab',
  'previous_page',
  'next_page',
  'get_dropdown_options',
] as const

function reindex(steps: ReplayStep[]): ReplayStep[] {
  return steps.map((step, i) => ({ ...step, index: i + 1 }))
}

function emptyStep(action = 'wait'): ReplayStep {
  return {
    index: 1,
    action,
    args: action === 'wait' ? { seconds: 1 } : {},
  }
}

function stepSummary(step: ReplayStep): string {
  if (step.element_label) return step.element_label
  const args = step.args || {}
  if (typeof args.url === 'string') return args.url
  if (typeof args.text === 'string') return args.text
  if (typeof args.keys === 'string') return args.keys
  if (typeof args.xpath === 'string') return args.xpath
  if (typeof args.css_selector === 'string') return String(args.css_selector)
  if (typeof args.seconds === 'number') return `${args.seconds}s`
  return ''
}

function argString(args: Record<string, unknown>, key: string): string {
  const value = args[key]
  if (value == null) return ''
  return String(value)
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  task: ProjectTask | null
  /** When true, create a new task instead of updating. */
  mode?: 'edit' | 'create'
  onSaveTask: (payload: {
    projectId: string
    taskId?: string
    name?: string | null
    task: string
    success_criteria: string
    headless: boolean
    max_steps: number
    cdp_url?: string
    fresh_profile?: boolean
  }) => Promise<void>
}

export default function TestEditorDialog({
  open,
  onOpenChange,
  projectId,
  task,
  mode = 'edit',
  onSaveTask,
}: Props) {
  const isCreate = mode === 'create' || !task
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
    enabled: open && isCreate,
  })
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const [criteria, setCriteria] = useState('')
  const [maxSteps, setMaxSteps] = useState(100)
  const [headless, setHeadless] = useState(false)
  const [freshProfile, setFreshProfile] = useState(true)
  const [steps, setSteps] = useState<ReplayStep[]>([])
  const [stepsLoading, setStepsLoading] = useState(false)
  const [stepsError, setStepsError] = useState<string | null>(null)
  const [stepsDirty, setStepsDirty] = useState(false)
  const [expandedStep, setExpandedStep] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const trainedRunId = task?.has_trained_replay ? task.last_trained_run_id : null

  useEffect(() => {
    if (!open) return
    setSaveError(null)
    setStepsDirty(false)
    setExpandedStep(null)
    if (task && !isCreate) {
      setName(task.name ?? '')
      setPrompt(task.task)
      setCriteria(task.success_criteria ?? '')
      setMaxSteps(task.max_steps)
      setHeadless(task.headless)
      setFreshProfile(task.fresh_profile ?? true)
    } else {
      setName('')
      setPrompt('')
      setCriteria('')
      setMaxSteps(100)
      setHeadless(false)
      setFreshProfile(config?.fresh_profile ?? true)
      setSteps([])
      setStepsError(null)
    }
  }, [open, task, isCreate, config?.fresh_profile])

  useEffect(() => {
    if (!open || !trainedRunId || isCreate) {
      setSteps([])
      setStepsError(null)
      setStepsLoading(false)
      return
    }
    let cancelled = false
    setStepsLoading(true)
    setStepsError(null)
    getRunReplay(trainedRunId)
      .then((data) => {
        if (!cancelled) {
          setSteps(reindex(data.replay_steps))
          setStepsDirty(false)
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setSteps([])
          setStepsError(err.message || 'Failed to load trained steps')
        }
      })
      .finally(() => {
        if (!cancelled) setStepsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, trainedRunId, isCreate])

  function updateStep(index: number, patch: Partial<ReplayStep>) {
    setSteps((prev) =>
      reindex(
        prev.map((s, i) => (i === index ? { ...s, ...patch, args: patch.args ?? s.args } : s)),
      ),
    )
    setStepsDirty(true)
  }

  function updateStepArg(index: number, key: string, value: string) {
    setSteps((prev) =>
      reindex(
        prev.map((s, i) => {
          if (i !== index) return s
          const nextArgs = { ...s.args }
          if (value === '') {
            delete nextArgs[key]
          } else if (key === 'seconds') {
            const n = Number(value)
            nextArgs[key] = Number.isFinite(n) ? n : value
          } else {
            nextArgs[key] = value
          }
          return { ...s, args: nextArgs }
        }),
      ),
    )
    setStepsDirty(true)
  }

  function moveStep(index: number, dir: -1 | 1) {
    const target = index + dir
    if (target < 0 || target >= steps.length) return
    setSteps((prev) => {
      const next = [...prev]
      ;[next[index], next[target]] = [next[target], next[index]]
      return reindex(next)
    })
    setStepsDirty(true)
    setExpandedStep((cur) => {
      if (cur === index) return target
      if (cur === target) return index
      return cur
    })
  }

  function removeStep(index: number) {
    setSteps((prev) => reindex(prev.filter((_, i) => i !== index)))
    setStepsDirty(true)
    setExpandedStep(null)
  }

  function addStep() {
    setSteps((prev) => reindex([...prev, emptyStep()]))
    setStepsDirty(true)
    setExpandedStep(steps.length)
  }

  async function handleSave() {
    if (!prompt.trim()) {
      setSaveError('Task prompt is required')
      return
    }
    if (!criteria.trim()) {
      setSaveError('Success criteria is required')
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      await onSaveTask({
        projectId,
        taskId: isCreate ? undefined : task?.id,
        name: name.trim() || null,
        task: prompt.trim(),
        success_criteria: criteria.trim(),
        headless,
        max_steps: maxSteps,
        cdp_url: undefined,
        fresh_profile: freshProfile,
      })
      if (!isCreate && trainedRunId && stepsDirty) {
        await updateRunReplay(trainedRunId, reindex(steps))
      }
      onOpenChange(false)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isCreate ? 'Add test' : 'Edit test'}</DialogTitle>
          <DialogDescription>
            {isCreate
              ? 'Create a test for this project. Train it with a successful run to unlock editable automatic steps.'
              : 'Update test settings and, when trained, the automatic execution steps.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-1">
          <section className="space-y-3 rounded-xl border border-border/80 bg-muted/20 p-3.5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Basics
              </p>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Identity and what the agent should accomplish.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="test-name">Name</Label>
              <Input
                id="test-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Login flow"
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="test-prompt">Task prompt</Label>
              <Textarea
                id="test-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                placeholder="What should the agent do?"
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="test-criteria">Success criteria</Label>
              <Textarea
                id="test-criteria"
                value={criteria}
                onChange={(e) => setCriteria(e.target.value)}
                rows={2}
                placeholder="How do we know it passed?"
                disabled={saving}
              />
            </div>
          </section>

          <section className="space-y-3 rounded-xl border border-border/80 bg-muted/20 p-3.5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Execution
              </p>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Browser and step limits for this test.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="test-max-steps">Max steps</Label>
                <Input
                  id="test-max-steps"
                  type="number"
                  min={1}
                  value={maxSteps}
                  onChange={(e) => setMaxSteps(Number(e.target.value) || 1)}
                  disabled={saving}
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-6">
              <div className="flex items-center gap-2">
                <Switch
                  id="test-headless"
                  checked={headless}
                  onCheckedChange={setHeadless}
                  disabled={saving}
                />
                <Label htmlFor="test-headless">Headless</Label>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  id="test-fresh"
                  checked={freshProfile}
                  onCheckedChange={setFreshProfile}
                  disabled={saving}
                />
                <Label htmlFor="test-fresh">Fresh profile</Label>
              </div>
            </div>
          </section>

          {!isCreate && (
            <section className="space-y-3 rounded-xl border border-border/80 bg-muted/20 p-3.5">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Trained steps
                  </p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    {trainedRunId
                      ? 'These steps run in Automatic mode. Reorder, edit, or remove as needed.'
                      : 'Complete a successful training run to capture editable steps.'}
                  </p>
                </div>
                {trainedRunId && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={addStep}
                    disabled={saving || stepsLoading}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Step
                  </Button>
                )}
              </div>

              {stepsLoading && (
                <p className="text-xs text-muted-foreground flex items-center gap-2 py-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Loading steps…
                </p>
              )}
              {stepsError && (
                <p className="text-xs text-destructive" role="alert">
                  {stepsError}
                </p>
              )}

              {!stepsLoading && trainedRunId && steps.length === 0 && !stepsError && (
                <p className="text-xs text-muted-foreground italic py-2">No steps yet.</p>
              )}

              <ul className="space-y-1.5">
                {steps.map((step, index) => {
                  const expanded = expandedStep === index
                  const panelId = `replay-step-${index}`
                  return (
                    <li
                      key={`${step.index}-${step.action}-${index}`}
                      className="rounded-lg border border-border bg-card/50 overflow-hidden transition-colors"
                    >
                      <div className="flex items-center gap-1 px-2 py-1.5">
                        <span className="text-[10px] mono text-muted-foreground w-5 shrink-0">
                          {step.index}
                        </span>
                        <button
                          type="button"
                          className="flex-1 min-w-0 text-left rounded px-1 py-0.5 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => setExpandedStep(expanded ? null : index)}
                          aria-expanded={expanded}
                          aria-controls={panelId}
                        >
                          <span className="text-xs font-medium mono">{step.action}</span>
                          {stepSummary(step) && (
                            <span className="text-xs text-muted-foreground ml-2 truncate">
                              {stepSummary(step)}
                            </span>
                          )}
                        </button>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() => moveStep(index, -1)}
                              disabled={index === 0 || saving}
                              aria-label="Move step up"
                            >
                              <ChevronUp className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Move up</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() => moveStep(index, 1)}
                              disabled={index === steps.length - 1 || saving}
                              aria-label="Move step down"
                            >
                              <ChevronDown className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Move down</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground hover:text-destructive"
                              onClick={() => removeStep(index)}
                              disabled={saving}
                              aria-label="Remove step"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Remove step</TooltipContent>
                        </Tooltip>
                      </div>
                      {expanded && (
                        <div
                          id={panelId}
                          className="border-t border-border px-3 py-2.5 space-y-2 animate-in fade-in-0 slide-in-from-top-1 duration-200"
                        >
                          <div className="space-y-1">
                            <Label className="text-xs">Action</Label>
                            <Select
                              value={step.action}
                              onValueChange={(value) => updateStep(index, { action: value })}
                              disabled={saving}
                            >
                              <SelectTrigger className="h-8 text-xs">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {REPLAY_ACTIONS.map((action) => (
                                  <SelectItem key={action} value={action} className="text-xs mono">
                                    {action}
                                  </SelectItem>
                                ))}
                                {!REPLAY_ACTIONS.includes(
                                  step.action as (typeof REPLAY_ACTIONS)[number],
                                ) && (
                                  <SelectItem value={step.action} className="text-xs mono">
                                    {step.action}
                                  </SelectItem>
                                )}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {(
                              [
                                ['url', 'URL'],
                                ['text', 'Text'],
                                ['keys', 'Keys'],
                                ['seconds', 'Seconds'],
                                ['xpath', 'XPath'],
                                ['css_selector', 'CSS'],
                              ] as const
                            ).map(([key, label]) => (
                              <div key={key} className="space-y-1">
                                <Label className="text-[10px] text-muted-foreground">{label}</Label>
                                <Input
                                  className={cn('h-8 text-xs', key !== 'seconds' && 'mono')}
                                  value={argString(step.args, key)}
                                  onChange={(e) => updateStepArg(index, key, e.target.value)}
                                  disabled={saving}
                                />
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>
          )}

          {saveError && (
            <p className="text-sm text-destructive" role="alert">
              {saveError}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleSave()}
            disabled={saving || !prompt.trim() || !criteria.trim()}
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {isCreate ? 'Create test' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
