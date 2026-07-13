import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Globe, Loader2, Play } from 'lucide-react'
import { getConfig, listWebsites, startRun } from '@/api'
import { useWebsites } from '@/hooks/useWebsites'
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
import { Card } from '@/components/ui/card'

const NO_WEBSITE = '__none__'

interface Props {
  onClose: () => void
  redirectOnStart?: boolean
}

export default function NewRunModal({ onClose, redirectOnStart = true }: Props) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [task, setTask] = useState('')
  const [websiteId, setWebsiteId] = useState<string>(NO_WEBSITE)
  const [headless, setHeadless] = useState(false)
  const [freshProfile, setFreshProfile] = useState(false)
  const [maxSteps, setMaxSteps] = useState(100)
  const [cdpUrl, setCdpUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveToWebsite, setSaveToWebsite] = useState(false)
  const [websiteMode, setWebsiteMode] = useState<'new' | 'existing'>('existing')
  const [newWebsiteName, setNewWebsiteName] = useState('')
  const [saveWebsiteId, setSaveWebsiteId] = useState('')
  const { websites, createWebsite, addTaskToWebsite } = useWebsites()
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: getConfig })
  const { data: websiteList = [] } = useQuery({
    queryKey: ['websites'],
    queryFn: listWebsites,
  })

  const selectedWebsite =
    websiteId !== NO_WEBSITE ? websiteList.find((w) => w.id === websiteId) : null

  useEffect(() => {
    if (config) setFreshProfile(config.fresh_profile ?? false)
  }, [config])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!task.trim()) return
    setLoading(true)
    setError(null)
    try {
      let runWebsiteId = websiteId !== NO_WEBSITE ? websiteId : undefined

      const payload = {
        task: task.trim(),
        headless,
        max_steps: maxSteps,
        cdp_url: cdpUrl.trim() || undefined,
        fresh_profile: freshProfile,
        website_id: runWebsiteId,
      }

      if (saveToWebsite) {
        let targetWebsiteId = saveWebsiteId
        if (websiteMode === 'new' && newWebsiteName.trim()) {
          const website = await createWebsite({ name: newWebsiteName.trim() })
          targetWebsiteId = website.id
          runWebsiteId = runWebsiteId ?? website.id
        }
        if (targetWebsiteId) {
          await addTaskToWebsite({
            websiteId: targetWebsiteId,
            task: payload.task,
            headless: payload.headless,
            max_steps: payload.max_steps,
            cdp_url: payload.cdp_url,
            fresh_profile: payload.fresh_profile ?? false,
          })
          if (!runWebsiteId) runWebsiteId = targetWebsiteId
        }
      }

      const run = await startRun({ ...payload, website_id: runWebsiteId })
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
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New QA Run</DialogTitle>
          <DialogDescription>
            Describe what the agent should test. Optionally attach a website for shared context
            like credentials.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="website">Website <span className="text-muted-foreground font-normal">(optional)</span></Label>
            <Select value={websiteId} onValueChange={setWebsiteId}>
              <SelectTrigger id="website">
                <SelectValue placeholder="No website — run standalone" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_WEBSITE}>No website</SelectItem>
                {websites.map((w) => (
                  <SelectItem key={w.id} value={w.id}>
                    {w.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedWebsite && (selectedWebsite.url || selectedWebsite.context_prompt) && (
              <div className="text-xs text-muted-foreground border border-border rounded-md p-3 space-y-1 bg-muted/30">
                <p className="flex items-center gap-1 text-foreground font-medium">
                  <Globe className="h-3 w-3 text-primary" />
                  {selectedWebsite.name} — passed to the agent
                </p>
                {selectedWebsite.url && (
                  <p className="mono text-primary break-all">{selectedWebsite.url}</p>
                )}
                {selectedWebsite.context_prompt && (
                  <p className="whitespace-pre-wrap leading-relaxed">{selectedWebsite.context_prompt}</p>
                )}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="task">Test task</Label>
            <Textarea
              id="task"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="e.g. Verify checkout completes after adding an item to cart."
              rows={4}
              required
            />
          </div>

          <div className="flex flex-wrap items-start gap-6">
            <div className="flex items-center gap-2">
              <Switch id="headless" checked={headless} onCheckedChange={setHeadless} />
              <Label htmlFor="headless" className="font-normal">Headless</Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch id="fresh" checked={freshProfile} onCheckedChange={setFreshProfile} />
              <Label htmlFor="fresh" className="font-normal">Isolated profile</Label>
            </div>
            <div className="flex-1 min-w-[10rem]">
              <Label className="text-xs text-muted-foreground">
                Max Steps: <span className="mono text-primary">{maxSteps}</span>
              </Label>
              <input
                type="range"
                min={10}
                max={200}
                step={10}
                value={maxSteps}
                onChange={(e) => setMaxSteps(Number(e.target.value))}
                className="w-full accent-primary mt-1"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="cdp">CDP URL <span className="text-muted-foreground font-normal">(optional)</span></Label>
            <Input
              id="cdp"
              value={cdpUrl}
              onChange={(e) => setCdpUrl(e.target.value)}
              placeholder="ws://localhost:9222/devtools/browser/..."
              className="mono text-sm"
            />
          </div>

          {error && (
            <p className="text-destructive text-sm bg-destructive/10 border border-destructive/30 rounded-md px-3 py-2">
              {error}
            </p>
          )}

          <Card className="p-3 space-y-3">
            <div className="flex items-center gap-2">
              <Switch id="save-website" checked={saveToWebsite} onCheckedChange={setSaveToWebsite} />
              <Label htmlFor="save-website" className="font-normal">Save test to website</Label>
            </div>
            {saveToWebsite && (
              <div className="space-y-2 pl-1">
                <div className="flex gap-4">
                  <label className="flex items-center gap-1.5 cursor-pointer text-sm">
                    <input
                      type="radio"
                      checked={websiteMode === 'new'}
                      onChange={() => setWebsiteMode('new')}
                      className="accent-primary"
                    />
                    New website
                  </label>
                  <label
                    className={`flex items-center gap-1.5 text-sm ${
                      websites.length === 0 ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'
                    }`}
                  >
                    <input
                      type="radio"
                      checked={websiteMode === 'existing'}
                      onChange={() => setWebsiteMode('existing')}
                      disabled={websites.length === 0}
                      className="accent-primary"
                    />
                    Existing website
                  </label>
                </div>
                {websiteMode === 'new' ? (
                  <Input
                    value={newWebsiteName}
                    onChange={(e) => setNewWebsiteName(e.target.value)}
                    placeholder="Website name…"
                  />
                ) : (
                  <Select value={saveWebsiteId} onValueChange={setSaveWebsiteId}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select a website…" />
                    </SelectTrigger>
                    <SelectContent>
                      {websites.map((w) => (
                        <SelectItem key={w.id} value={w.id}>
                          {w.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            )}
          </Card>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading || !task.trim()}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Starting…
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  Run
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
