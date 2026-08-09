import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Plus, Trash2, X } from 'lucide-react'
import { checkConfig, getConfig, getPricing, getWorkerStatus, isProviderApiKeySet, listChromeProfiles, savePricing, updateConfig } from '@/api'
import { defaultBaseUrl, defaultModel, isValidBaseUrlForProvider, coerceUiProvider, providerUsesApiKey, UI_PROVIDERS } from '@/providers'
import type { BrowserSessionMode, ChromeProfile, Config, PricingEntry } from '@/types'
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

const PROFILE_APP_DEFAULT = '__app_default__'
const PROFILE_CUSTOM = '__custom__'
/** Display-only stand-in when a key is stored; never sent to the server. */
const MASKED_API_KEY = '********'

const AGENT_ROLES = [
  {
    id: 'navigation' as const,
    title: 'Navigation',
    description: 'Navigator and criteria checker',
  },
  {
    id: 'planning' as const,
    title: 'Planning',
    description: 'Planner, actor-critic, and HITL debrief',
  },
]

type AgentRoleId = (typeof AGENT_ROLES)[number]['id']

type RoleFormState = {
  provider: string
  baseUrl: string
  model: string
  apiKey: string
  openrouterProvider: string
}

function emptyRoleForm(): RoleFormState {
  return {
    provider: '',
    baseUrl: '',
    model: '',
    apiKey: '',
    openrouterProvider: '',
  }
}

function roleFormFromConfig(role: AgentRoleId, next: Config): RoleFormState {
  const roleConfig = next.roles?.[role]
  const provider = coerceUiProvider(roleConfig?.provider ?? next.provider)
  return {
    provider,
    baseUrl: roleConfig?.base_url ?? next.base_url,
    model: roleConfig?.model ?? next.model,
    apiKey: isProviderApiKeySet(provider, next) ? MASKED_API_KEY : '',
    openrouterProvider: roleConfig?.openrouter_provider ?? next.openrouter_provider ?? '',
  }
}

function inferProfileSelection(
  chromeUserData: string,
  chromeProfileDirectory: string,
  profiles: ChromeProfile[],
): string {
  if (!chromeUserData && !chromeProfileDirectory) {
    return PROFILE_APP_DEFAULT
  }
  if (chromeProfileDirectory) {
    const id = `${chromeUserData}|${chromeProfileDirectory}`
    if (profiles.some((profile) => profile.id === id)) {
      return id
    }
  }
  return PROFILE_CUSTOM
}

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

  const { data: chromeProfiles = [] } = useQuery({
    queryKey: ['chrome-profiles'],
    queryFn: listChromeProfiles,
    refetchOnWindowFocus: false,
    refetchInterval: 10_000,
  })

  const { data: workerStatus } = useQuery({
    queryKey: ['worker-status'],
    queryFn: getWorkerStatus,
    refetchInterval: 5_000,
  })

  const [roleForms, setRoleForms] = useState<Record<AgentRoleId, RoleFormState>>({
    navigation: emptyRoleForm(),
    planning: emptyRoleForm(),
  })
  const [freshProfile, setFreshProfile] = useState(true)
  const [chromeUserData, setChromeUserData] = useState('')
  const [chromeProfileDirectory, setChromeProfileDirectory] = useState('')
  const [profileSelection, setProfileSelection] = useState(PROFILE_APP_DEFAULT)
  const [dirty, setDirty] = useState(false)
  const [checkingRole, setCheckingRole] = useState<AgentRoleId | null>(null)
  const [checkResults, setCheckResults] = useState<
    Partial<Record<AgentRoleId, { ok: boolean; error?: string; provider_name?: string }>>
  >({})
  const [pricing, setPricing] = useState<PricingEntry[]>([])
  const [pricingSaved, setPricingSaved] = useState(false)

  function applyConfig(next: Config) {
    setRoleForms({
      navigation: roleFormFromConfig('navigation', next),
      planning: roleFormFromConfig('planning', next),
    })
    setFreshProfile(next.fresh_profile ?? true)
    setChromeUserData(next.chrome_user_data ?? '')
    setChromeProfileDirectory(next.chrome_profile_directory ?? '')
    setProfileSelection(
      inferProfileSelection(
        next.chrome_user_data ?? '',
        next.chrome_profile_directory ?? '',
        chromeProfiles,
      ),
    )
  }

  useEffect(() => {
    if (config && !dirty) {
      applyConfig(config)
    }
  }, [config, dirty, chromeProfiles])

  function updateRoleForm(role: AgentRoleId, patch: Partial<RoleFormState>) {
    setDirty(true)
    setRoleForms((prev) => ({ ...prev, [role]: { ...prev[role], ...patch } }))
  }

  function handleProviderChange(role: AgentRoleId, next: string) {
    const canonical = coerceUiProvider(next)
    const saved = config?.provider_settings?.[canonical]
    const savedBaseUrl = saved?.base_url || ''
    const baseUrlValid = isValidBaseUrlForProvider(canonical, savedBaseUrl)
    const lastModel = config?.selected_models?.[canonical]?.trim()
    const savedModels = saved?.models ?? []
    const currentRole = roleForms[role]
    let nextModel = defaultModel(canonical)
    if (lastModel) {
      nextModel = lastModel
    } else if (canonical === coerceUiProvider(config?.roles?.[role]?.provider ?? config?.provider ?? '')) {
      nextModel = config?.roles?.[role]?.model || config?.model || defaultModel(canonical)
    } else if (baseUrlValid && savedModels.length > 0) {
      nextModel = savedModels[0]
    }
    updateRoleForm(role, {
      provider: canonical,
      baseUrl: baseUrlValid ? savedBaseUrl : defaultBaseUrl(canonical),
      model: nextModel,
      apiKey: isProviderApiKeySet(canonical, config) ? MASKED_API_KEY : '',
      openrouterProvider: canonical === 'openrouter' ? currentRole.openrouterProvider : '',
    })
  }

  function apiKeyForRequest(role: AgentRoleId): string | undefined {
    const trimmed = roleForms[role].apiKey.trim()
    if (!trimmed || trimmed === MASKED_API_KEY) return undefined
    return trimmed
  }

  function rolePayload(role: AgentRoleId) {
    const form = roleForms[role]
    return {
      provider: form.provider,
      base_url: form.baseUrl,
      model: form.model,
      api_key: apiKeyForRequest(role),
      openrouter_provider: form.provider === 'openrouter' ? form.openrouterProvider.trim() : undefined,
    }
  }

  useEffect(() => {
    if (pricingData) setPricing(pricingData)
  }, [pricingData])

  const connectOnline = Boolean(workerStatus?.online ?? config?.connect_online)

  const saveMutation = useMutation({
    mutationFn: () =>
      updateConfig({
        roles: {
          navigation: rolePayload('navigation'),
          planning: rolePayload('planning'),
        },
        fresh_profile: freshProfile,
        chrome_user_data: chromeUserData,
        chrome_profile_directory: chromeProfileDirectory,
        cdp_url: '',
      }),
    onSuccess: (saved) => {
      queryClient.setQueryData(['config'], saved)
      applyConfig(saved)
      setDirty(false)
      queryClient.invalidateQueries({ queryKey: ['chrome-profiles'] })
      queryClient.invalidateQueries({ queryKey: ['worker-status'] })
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

  async function handleCheck(role: AgentRoleId) {
    setCheckingRole(role)
    setCheckResults((prev) => ({ ...prev, [role]: undefined }))
    const result = await checkConfig(rolePayload(role)).catch((e) => ({
      ok: false,
      error: String(e),
    }))
    setCheckResults((prev) => ({ ...prev, [role]: result }))
    setCheckingRole(null)
  }

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

          <TabsContent value="llm" className="space-y-8">
            <p className="text-sm text-muted-foreground">
              Choose provider and model per agent role. API keys are shared per provider; the
              available-model list is shared on this server.
            </p>

            {AGENT_ROLES.map((role) => (
              <LlmRoleSection
                key={role.id}
                roleId={role.id}
                title={role.title}
                description={role.description}
                form={roleForms[role.id]}
                config={config}
                checking={checkingRole === role.id}
                checkResult={checkResults[role.id]}
                onProviderChange={(value) => handleProviderChange(role.id, value)}
                onBaseUrlChange={(value) => updateRoleForm(role.id, { baseUrl: value })}
                onModelChange={(value) => updateRoleForm(role.id, { model: value })}
                onOpenrouterProviderChange={(value) =>
                  updateRoleForm(role.id, { openrouterProvider: value })
                }
                onApiKeyChange={(value) => updateRoleForm(role.id, { apiKey: value })}
                onApiKeyFocus={() => {
                  if (roleForms[role.id].apiKey === MASKED_API_KEY) {
                    updateRoleForm(role.id, { apiKey: '' })
                  }
                }}
                onApiKeyBlur={() => {
                  const provider = roleForms[role.id].provider
                  if (!roleForms[role.id].apiKey.trim() && isProviderApiKeySet(provider, config)) {
                    updateRoleForm(role.id, { apiKey: MASKED_API_KEY })
                  }
                }}
                onCheck={() => handleCheck(role.id)}
              />
            ))}

            <SaveBar
              pending={saveMutation.isPending}
              success={saveMutation.isSuccess}
              error={saveMutation.isError ? saveMutation.error : null}
              onSave={() => saveMutation.mutate()}
            />
          </TabsContent>

          <TabsContent value="browser" className="space-y-5">
            <p className="text-sm text-muted-foreground">
              Choose how Chrome runs on the Connect machine. Profiles are listed from the
              connected Connect app — the server never launches Chrome itself.
            </p>

            <Card>
              <CardContent className="p-0 divide-y divide-border text-sm">
                <InfoRow
                  label="Connect"
                  value={
                    connectOnline
                      ? `Online${workerStatus?.browser_state && workerStatus.browser_state !== 'idle' ? ` · ${workerStatus.browser_state}` : ''}`
                      : 'Offline — start the Connect app to run browser tasks'
                  }
                />
                {config && (
                  <>
                    <InfoRow
                      label="Session mode"
                      value={sessionModeLabel(config.browser_session_mode)}
                    />
                    <InfoRow
                      label="Active profile"
                      value={
                        config.effective_chrome_profile
                        || (config.browser_session_mode === 'ephemeral'
                          ? 'Fresh profile (discarded after each run)'
                          : config.effective_chrome_user_data
                            || '—')
                      }
                    />
                  </>
                )}
              </CardContent>
            </Card>

            {!connectOnline && (
              <p className="text-sm text-amber-700 dark:text-amber-400">
                Connect is offline. Runs will fail until the Connect app is logged in and connected.
              </p>
            )}

            <div className="space-y-2">
              <Label htmlFor="chrome-profile-select">Chrome profile</Label>
              <Select
                value={profileSelection}
                onValueChange={(value) => {
                  setDirty(true)
                  setProfileSelection(value)
                  if (value === PROFILE_APP_DEFAULT) {
                    setChromeUserData('')
                    setChromeProfileDirectory('')
                  } else if (value === PROFILE_CUSTOM) {
                    setChromeProfileDirectory('')
                  } else {
                    const profile = chromeProfiles.find((item) => item.id === value)
                    if (profile) {
                      setChromeUserData(profile.user_data_dir)
                      setChromeProfileDirectory(profile.profile_directory)
                    }
                  }
                }}
                disabled={freshProfile}
              >
                <SelectTrigger id="chrome-profile-select" className="text-sm">
                  <SelectValue placeholder="Select a profile" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={PROFILE_APP_DEFAULT}>
                    App default (smart-automator)
                  </SelectItem>
                  {chromeProfiles.map((profile) => (
                    <SelectItem key={profile.id} value={profile.id}>
                      {profile.name} — {profile.browser}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {freshProfile
                  ? 'Disabled while fresh profile is on — each run starts with a blank browser on the Connect machine.'
                  : !connectOnline
                    ? 'Profiles appear when Connect is online.'
                    : chromeProfiles.length === 0
                      ? 'No system profiles advertised yet — Connect will use the app default profile.'
                      : profileSelection === PROFILE_APP_DEFAULT
                        ? 'Uses the Connect app default profile directory. Cookies and history persist between runs.'
                        : 'System profiles are mirrored on the Connect machine before launch.'}
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
                <Label htmlFor="fresh-profile" className="font-normal">Fresh profile</Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Throw away all browser state after each run on the Connect machine — on by default
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
                      <SelectItem value="openrouter">openrouter</SelectItem>
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
                  {AGENT_ROLES.map((role) => {
                    const roleConfig = config.roles?.[role.id]
                    return (
                      <div key={role.id} className="px-4 py-3 space-y-2">
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">{role.title}</p>
                        <InfoRow label="Provider" value={roleConfig?.provider ?? config.provider} />
                        <InfoRow label="Model" value={roleConfig?.model ?? config.model} />
                        <InfoRow label="Base URL" value={roleConfig?.base_url ?? config.base_url} />
                        {(roleConfig?.provider ?? config.provider) === 'openrouter' && (
                          <InfoRow
                            label="Upstream provider"
                            value={roleConfig?.openrouter_provider?.trim() || 'Auto'}
                          />
                        )}
                        <InfoRow
                          label="API Key Set"
                          value={(roleConfig?.api_key_set ?? config.api_key_set) ? 'Yes' : 'No'}
                        />
                      </div>
                    )
                  })}
                  <InfoRow label="Connect" value={config.connect_online ? 'Online' : 'Offline'} />
                  <InfoRow label="Fresh profile" value={config.fresh_profile ? 'Yes' : 'No'} />
                  <InfoRow
                    label="Session Mode"
                    value={sessionModeLabel(config.browser_session_mode)}
                  />
                  <InfoRow
                    label="Profile"
                    value={config.effective_chrome_profile || config.effective_chrome_user_data || '(default)'}
                  />
                </CardContent>
              </Card>
            )}
          </TabsContent>
        </Tabs>
      </ScrollArea>
    </div>
  )
}

function LlmRoleSection({
  roleId,
  title,
  description,
  form,
  config,
  checking,
  checkResult,
  onProviderChange,
  onBaseUrlChange,
  onModelChange,
  onOpenrouterProviderChange,
  onApiKeyChange,
  onApiKeyFocus,
  onApiKeyBlur,
  onCheck,
}: {
  roleId: AgentRoleId
  title: string
  description: string
  form: RoleFormState
  config: Config | undefined
  checking: boolean
  checkResult?: { ok: boolean; error?: string; provider_name?: string }
  onProviderChange: (value: string) => void
  onBaseUrlChange: (value: string) => void
  onModelChange: (value: string) => void
  onOpenrouterProviderChange: (value: string) => void
  onApiKeyChange: (value: string) => void
  onApiKeyFocus: () => void
  onApiKeyBlur: () => void
  onCheck: () => void
}) {
  const providerApiKeySet = isProviderApiKeySet(form.provider, config)
  const modelOptions = config?.provider_settings?.[form.provider]?.models ?? []

  return (
    <section className="space-y-4 rounded-lg border border-border p-4">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
      </div>

      <div className="space-y-2">
        <Label>Provider</Label>
        <Select value={form.provider} onValueChange={onProviderChange}>
          <SelectTrigger>
            <SelectValue placeholder="Select provider" />
          </SelectTrigger>
          <SelectContent>
            {UI_PROVIDERS.map((item) => (
              <SelectItem key={`${roleId}-${item.id}`} value={item.id}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label>Base URL</Label>
        <Input value={form.baseUrl} onChange={(e) => onBaseUrlChange(e.target.value)} className="mono" />
      </div>

      <ModelField
        key={`${roleId}-${form.provider}`}
        model={form.model}
        modelOptions={modelOptions}
        onModelChange={onModelChange}
      />

      {form.provider === 'openrouter' && (
        <div className="space-y-2">
          <Label>Upstream provider</Label>
          <Input
            value={form.openrouterProvider}
            onChange={(e) => onOpenrouterProviderChange(e.target.value)}
            placeholder="Auto"
            className="mono"
          />
          <p className="text-xs text-muted-foreground">
            OpenRouter provider slug (e.g. together, deepinfra). Leave empty for Auto.
          </p>
        </div>
      )}

      {providerUsesApiKey(form.provider) && (
        <div className="space-y-2">
          <Label>
            API Key{' '}
            {providerApiKeySet && (
              <span className="text-success font-normal text-xs">(set)</span>
            )}
          </Label>
          <Input
            type="password"
            value={form.apiKey}
            onChange={(e) => onApiKeyChange(e.target.value)}
            onFocus={onApiKeyFocus}
            onBlur={onApiKeyBlur}
            autoComplete="off"
            placeholder={providerApiKeySet ? undefined : 'Enter API key…'}
            className="mono"
          />
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button variant="outline" onClick={onCheck} disabled={checking}>
          {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Test Connection'}
        </Button>
        {checkResult && (
          <span
            className={`text-sm flex items-center gap-1 ${checkResult.ok ? 'text-success' : 'text-destructive'}`}
          >
            {checkResult.ok ? (
              <>
                <Check className="h-4 w-4" />{' '}
                {checkResult.provider_name
                  ? `Connected (${checkResult.provider_name})`
                  : 'Connected'}
              </>
            ) : (
              <>
                <X className="h-4 w-4" /> {checkResult.error ?? 'Failed'}
              </>
            )}
          </span>
        )}
      </div>
    </section>
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
      return 'Connect (remote Chrome)'
    case 'persistent':
      return 'Persistent (on-disk profile)'
    case 'ephemeral':
      return 'Fresh profile (discarded after each run)'
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
