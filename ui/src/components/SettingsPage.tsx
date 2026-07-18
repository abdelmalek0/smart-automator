import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Plus, Trash2, X } from 'lucide-react'
import { checkConfig, getConfig, getPricing, isProviderApiKeySet, savePricing, updateConfig } from '@/api'
import { defaultBaseUrl, defaultModel, isValidBaseUrlForProvider, normalizeProvider, providerUsesApiKey } from '@/providers'
import type { BrowserSessionMode, Config, PricingEntry } from '@/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'

export default function SettingsPage() {
  const queryClient = useQueryClient()

  const { data: config, isLoading } = useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
    refetchOnWindowFocus: false,
  })

  const { data: pricingData } = useQuery({
    queryKey: ['pricing'],
    queryFn: getPricing,
  })

  const [provider, setProvider] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [freshProfile, setFreshProfile] = useState(false)
  const [chromeUserData, setChromeUserData] = useState('')
  const [cdpUrl, setCdpUrl] = useState('')
  const [dirty, setDirty] = useState(false)
  const [checking, setChecking] = useState(false)
  const [checkResult, setCheckResult] = useState<{ ok: boolean; error?: string } | null>(null)
  const [pricing, setPricing] = useState<PricingEntry[]>([])
  const [pricingSaved, setPricingSaved] = useState(false)

  function applyConfig(next: Config) {
    setProvider(normalizeProvider(next.provider))
    setBaseUrl(next.base_url)
    setModel(next.model)
    setFreshProfile(next.fresh_profile ?? false)
    setChromeUserData(next.chrome_user_data ?? '')
    setCdpUrl(next.cdp_url ?? '')
  }

  useEffect(() => {
    if (config && !dirty) {
      applyConfig(config)
    }
  }, [config, dirty])

  function handleProviderChange(next: string) {
    const canonical = normalizeProvider(next)
    setDirty(true)
    setProvider(canonical)
    setApiKey('')
    const saved = config?.provider_settings?.[canonical]
    const savedBaseUrl = saved?.base_url || ''
    const savedModel = saved?.model || ''
    const baseUrlValid = isValidBaseUrlForProvider(canonical, savedBaseUrl)
    setBaseUrl(baseUrlValid ? savedBaseUrl : defaultBaseUrl(canonical))
    setModel(baseUrlValid && savedModel ? savedModel : defaultModel(canonical))
  }

  useEffect(() => {
    if (pricingData) setPricing(pricingData)
  }, [pricingData])

  const saveMutation = useMutation({
    mutationFn: () =>
      updateConfig({
        provider,
        base_url: baseUrl,
        model,
        api_key: apiKey || undefined,
        fresh_profile: freshProfile,
        chrome_user_data: chromeUserData,
        cdp_url: cdpUrl,
      }),
    onSuccess: (saved) => {
      queryClient.setQueryData(['config'], saved)
      applyConfig(saved)
      setApiKey('')
      setDirty(false)
    },
  })

  const savePricingMutation = useMutation({
    mutationFn: () => savePricing(pricing),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pricing'] })
      setPricingSaved(true)
      setTimeout(() => setPricingSaved(false), 2000)
    },
  })

  function updatePricingRow(index: number, field: keyof PricingEntry, value: string) {
    setPricing((prev) =>
      prev.map((row, i) =>
        i === index
          ? { ...row, [field]: ['input', 'output', 'cache_read'].includes(field) ? parseFloat(value) || 0 : value }
          : row,
      ),
    )
  }

  async function handleCheck() {
    setChecking(true)
    setCheckResult(null)
    const result = await checkConfig({
      provider,
      base_url: baseUrl,
      model,
      api_key: apiKey || undefined,
    }).catch((e) => ({ ok: false, error: String(e) }))
    setCheckResult(result)
    setChecking(false)
  }

  const providerApiKeySet = isProviderApiKeySet(provider, config)
  const modelOptions = config?.provider_settings?.[provider]?.models ?? []

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 px-6 pt-6 pb-0 border-b border-border">
        <h2 className="text-lg font-semibold mb-4">Settings</h2>
      </div>

      <ScrollArea className="flex-1 px-6 py-6">
        {isLoading && (
          <p className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </p>
        )}

        <Tabs defaultValue="llm" className="max-w-2xl">
          <TabsList className="mb-6">
            <TabsTrigger value="llm">LLM Provider</TabsTrigger>
            <TabsTrigger value="browser">Browser</TabsTrigger>
            <TabsTrigger value="pricing">Token Pricing</TabsTrigger>
            <TabsTrigger value="about">About</TabsTrigger>
          </TabsList>

          <TabsContent value="llm" className="space-y-5">
            <div className="space-y-2">
              <Label>Provider</Label>
              <Select value={provider} onValueChange={handleProviderChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select provider" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ollama-cloud">Ollama Cloud</SelectItem>
                  <SelectItem value="ollama">Ollama (local)</SelectItem>
                  <SelectItem value="google">Google Gemini</SelectItem>
                  <SelectItem value="groq">Groq</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Base URL</Label>
              <Input
                value={baseUrl}
                onChange={(e) => {
                  setDirty(true)
                  setBaseUrl(e.target.value)
                }}
                className="mono"
              />
            </div>

            <ModelField
              key={provider}
              model={model}
              modelOptions={modelOptions}
              onModelChange={(value) => {
                setDirty(true)
                setModel(value)
              }}
            />

            <div className="space-y-2">
              {providerUsesApiKey(provider) && (
                <>
                  <Label>
                    API Key{' '}
                    {providerApiKeySet && (
                      <span className="text-success font-normal text-xs">(set)</span>
                    )}
                  </Label>
                  <Input
                    type="password"
                    value={apiKey}
                    onChange={(e) => {
                      setDirty(true)
                      setApiKey(e.target.value)
                    }}
                    placeholder={providerApiKeySet ? '••••••••••••' : 'Enter API key…'}
                    className="mono"
                  />
                </>
              )}
            </div>

            <div className="flex items-center gap-3">
              <Button variant="outline" onClick={handleCheck} disabled={checking}>
                {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Test Connection'}
              </Button>
              {checkResult && (
                <span className={`text-sm flex items-center gap-1 ${checkResult.ok ? 'text-success' : 'text-destructive'}`}>
                  {checkResult.ok ? (
                    <>
                      <Check className="h-4 w-4" /> Connected
                    </>
                  ) : (
                    <>
                      <X className="h-4 w-4" /> {checkResult.error ?? 'Failed'}
                    </>
                  )}
                </span>
              )}
            </div>

            <SaveBar
              pending={saveMutation.isPending}
              success={saveMutation.isSuccess}
              error={saveMutation.isError ? saveMutation.error : null}
              onSave={() => saveMutation.mutate()}
            />
          </TabsContent>

          <TabsContent value="browser" className="space-y-5">
            <p className="text-sm text-muted-foreground">
              Control how browser state (logins, cookies, history) is kept between runs.
              Use a persistent on-disk profile by default, attach to Chrome via CDP, or enable
              isolated profile for a clean throwaway browser each run.
            </p>

            {config && (
              <Card>
                <CardContent className="p-0 divide-y divide-border text-sm">
                  <InfoRow
                    label="Session mode"
                    value={sessionModeLabel(config.browser_session_mode)}
                  />
                  <InfoRow
                    label="Active profile"
                    value={
                      config.browser_session_mode === 'persistent'
                        ? config.effective_chrome_user_data
                        : config.browser_session_mode === 'cdp'
                          ? 'Attached via CDP'
                          : 'Ephemeral (discarded after each run)'
                    }
                  />
                </CardContent>
              </Card>
            )}

            <div className="space-y-2">
              <Label htmlFor="cdp-url">CDP URL</Label>
              <Input
                id="cdp-url"
                value={cdpUrl}
                onChange={(e) => {
                  setDirty(true)
                  setCdpUrl(e.target.value)
                }}
                placeholder={`ws://127.0.0.1:${config?.cdp_port ?? 9222}`}
                className="mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Optional. Connect to an existing Chrome with remote debugging — uses that
                browser&apos;s profile and overrides the profile directory below.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="chrome-profile">Profile directory</Label>
              <Input
                id="chrome-profile"
                value={chromeUserData}
                onChange={(e) => {
                  setDirty(true)
                  setChromeUserData(e.target.value)
                }}
                placeholder={config?.default_chrome_user_data ?? '~/.local/share/smart-automator-chrome'}
                className="mono text-sm"
                disabled={freshProfile || Boolean(cdpUrl.trim())}
              />
              <p className="text-xs text-muted-foreground">
                {freshProfile
                  ? 'Disabled while isolated profile is on — each run starts with a blank browser.'
                  : cdpUrl.trim()
                    ? 'Not used while CDP URL is set.'
                    : 'Leave empty to use the default directory above. Cookies and history persist between runs.'}
              </p>
            </div>

            <div className="flex items-start gap-3">
              <Switch
                id="fresh-profile"
                checked={freshProfile}
                onCheckedChange={(value) => {
                  setDirty(true)
                  setFreshProfile(value)
                }}
              />
              <div>
                <Label htmlFor="fresh-profile" className="font-normal">Isolated Chrome profile</Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Throw away all browser state after each run — off by default
                </p>
              </div>
            </div>

            <SaveBar
              pending={saveMutation.isPending}
              success={saveMutation.isSuccess}
              error={saveMutation.isError ? saveMutation.error : null}
              onSave={() => saveMutation.mutate()}
            />
          </TabsContent>

          <TabsContent value="pricing" className="space-y-5">
            <p className="text-sm text-muted-foreground">
              USD per 1 million tokens. Used to calculate cost shown on each run.
            </p>

            <div className="space-y-2">
              {pricing.length === 0 && (
                <p className="text-sm text-muted-foreground italic py-4">
                  No entries yet — click Add Row to add a model.
                </p>
              )}
              {pricing.map((row, i) => (
                <div key={i} className="grid grid-cols-[100px_1fr_72px_72px_72px_32px] gap-2 items-center">
                  <Select
                    value={row.provider}
                    onValueChange={(v) => updatePricingRow(i, 'provider', v)}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="groq">groq</SelectItem>
                      <SelectItem value="google">google</SelectItem>
                      <SelectItem value="ollama-cloud">ollama-cloud</SelectItem>
                      <SelectItem value="ollama">ollama</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input
                    value={row.model}
                    onChange={(e) => updatePricingRow(i, 'model', e.target.value)}
                    placeholder="model-name"
                    className="h-8 text-xs mono"
                  />
                  {(['input', 'output', 'cache_read'] as const).map((field) => (
                    <Input
                      key={field}
                      type="number"
                      min="0"
                      step="0.01"
                      value={row[field]}
                      onChange={(e) => updatePricingRow(i, field, e.target.value)}
                      className="h-8 text-xs mono text-right"
                    />
                  ))}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    onClick={() => setPricing((p) => p.filter((_, j) => j !== i))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() =>
                  setPricing((p) => [
                    ...p,
                    { provider: 'groq', model: '', input: 0, output: 0, cache_read: 0 },
                  ])
                }
              >
                <Plus className="h-4 w-4" />
                Add Row
              </Button>
            </div>

            <div className="flex items-center gap-4 pt-4 border-t border-border">
              <Button onClick={() => savePricingMutation.mutate()} disabled={savePricingMutation.isPending}>
                {savePricingMutation.isPending ? 'Saving…' : 'Save Pricing'}
              </Button>
              {pricingSaved && (
                <span className="text-success text-sm flex items-center gap-1">
                  <Check className="h-4 w-4" /> Saved
                </span>
              )}
              {savePricingMutation.isError && (
                <span className="text-destructive text-sm">Failed to save</span>
              )}
            </div>
          </TabsContent>

          <TabsContent value="about">
            <p className="text-sm text-muted-foreground mb-4">Runtime configuration and diagnostics.</p>
            {config && (
              <Card>
                <CardContent className="p-0 divide-y divide-border">
                  <InfoRow label="Provider" value={config.provider} />
                  <InfoRow label="Model" value={config.model} />
                  <InfoRow label="Base URL" value={config.base_url} />
                  <InfoRow label="CDP Port" value={String(config.cdp_port)} />
                  <InfoRow label="CDP URL" value={config.cdp_url || '(not set)'} />
                  <InfoRow label="Fresh Profile" value={config.fresh_profile ? 'Yes' : 'No'} />
                  <InfoRow
                    label="Session Mode"
                    value={sessionModeLabel(config.browser_session_mode)}
                  />
                  <InfoRow
                    label="Profile Dir"
                    value={
                      config.browser_session_mode === 'persistent'
                        ? config.effective_chrome_user_data
                        : '(not used)'
                    }
                  />
                  <InfoRow label="API Key Set" value={config.api_key_set ? 'Yes' : 'No'} />
                </CardContent>
              </Card>
            )}
          </TabsContent>
        </Tabs>
      </ScrollArea>
    </div>
  )
}

function ModelField({
  model,
  modelOptions,
  onModelChange,
}: {
  model: string
  modelOptions: string[]
  onModelChange: (value: string) => void
}) {
  const CUSTOM = '__custom__'
  const inputRef = useRef<HTMLInputElement>(null)
  const hasSaved = modelOptions.length > 0
  const isSaved = hasSaved && modelOptions.includes(model)
  const [customMode, setCustomMode] = useState(() => hasSaved && !isSaved)

  useEffect(() => {
    if (!hasSaved) {
      setCustomMode(false)
      return
    }
    if (modelOptions.includes(model)) {
      setCustomMode(false)
    }
  }, [hasSaved, model, modelOptions])

  function enterCustom() {
    setCustomMode(true)
    onModelChange('')
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  function useSavedModels() {
    setCustomMode(false)
    if (!modelOptions.includes(model)) {
      onModelChange(modelOptions[0] ?? model)
    }
  }

  if (!hasSaved || customMode) {
    return (
      <div className="space-y-2">
        <Label>Model</Label>
        <Input
          ref={inputRef}
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
          className="mono"
          placeholder="Model name"
        />
        {hasSaved && (
          <button
            type="button"
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            onClick={useSavedModels}
          >
            Choose from saved models
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <Label>Model</Label>
      <Select
        value={model}
        onValueChange={(value) => (value === CUSTOM ? enterCustom() : onModelChange(value))}
      >
        <SelectTrigger className="mono">
          <SelectValue placeholder="Pick a model…" />
        </SelectTrigger>
        <SelectContent>
          {modelOptions.map((name) => (
            <SelectItem key={name} value={name} className="mono">
              {name}
            </SelectItem>
          ))}
          <SelectItem value={CUSTOM} className="text-muted-foreground">
            Custom model…
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}

function sessionModeLabel(mode: BrowserSessionMode): string {
  switch (mode) {
    case 'cdp':
      return 'CDP (attached Chrome)'
    case 'persistent':
      return 'Persistent (on-disk profile)'
    case 'ephemeral':
      return 'Ephemeral (throwaway per run)'
  }
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center px-4 py-3 gap-4">
      <span className="text-xs uppercase tracking-wide text-muted-foreground w-28 shrink-0">{label}</span>
      <span className="text-sm mono text-foreground break-all">{value}</span>
    </div>
  )
}

function SaveBar({
  pending,
  success,
  error,
  onSave,
}: {
  pending: boolean
  success: boolean
  error: unknown
  onSave: () => void
}) {
  return (
    <div className="flex items-center gap-4 pt-6 border-t border-border">
      <Button onClick={onSave} disabled={pending}>
        {pending ? 'Saving…' : 'Save'}
      </Button>
      {success && (
        <span className="text-success text-sm flex items-center gap-1">
          <Check className="h-4 w-4" /> Saved and applied
        </span>
      )}
      {error != null && Boolean(error) && (
        <span className="text-destructive text-sm">
          Failed: {error instanceof Error ? error.message : 'unknown'}
        </span>
      )}
    </div>
  )
}
