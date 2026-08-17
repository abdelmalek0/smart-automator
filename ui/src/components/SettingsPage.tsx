import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2 } from 'lucide-react'
import {
  checkConfig,
  getConfig,
  getPricing,
  getWorkerStatus,
  isProviderApiKeySet,
  listChromeProfiles,
  savePricing,
  updateConfig,
} from '@/api'
import {
  defaultBaseUrl,
  defaultModel,
  isValidBaseUrlForProvider,
  coerceUiProvider,
} from '@/providers'
import type { ChromeProfile, Config, PricingEntry } from '@/types'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import BrowserSettings from '@/components/settings/BrowserSettings'
import LlmSettings from '@/components/settings/LlmSettings'
import PricingSettings from '@/components/settings/PricingSettings'
import {
  MASKED_API_KEY,
  PROFILE_APP_DEFAULT,
  PROFILE_CUSTOM,
} from '@/components/settings/types'
import type { AgentRoleId, CheckResult, RoleFormState } from '@/components/settings/types'

type SettingsTab = 'llm' | 'browser' | 'pricing'

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

const TAB_COPY: Record<SettingsTab, string> = {
  llm: 'Provider and model per agent role. API keys are shared per provider.',
  browser: 'How Chrome runs on the Connect machine.',
  pricing: 'USD per million tokens, used for cost on each run.',
}

const tabTriggerClass =
  'rounded-none bg-transparent px-1 pb-2.5 pt-0 shadow-none border-b-2 border-transparent text-muted-foreground hover:text-foreground data-[state=active]:shadow-none data-[state=active]:bg-transparent data-[state=active]:border-primary data-[state=active]:text-foreground'

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<SettingsTab>('llm')

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
  const [checkResults, setCheckResults] = useState<Partial<Record<AgentRoleId, CheckResult>>>({})
  const [pricing, setPricing] = useState<PricingEntry[]>([])
  const [pricingDirty, setPricingDirty] = useState(false)
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

  useEffect(() => {
    if (pricingData && !pricingDirty) setPricing(pricingData)
  }, [pricingData, pricingDirty])

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
      setPricingDirty(false)
      setPricingSaved(true)
      setTimeout(() => setPricingSaved(false), 2000)
    },
  })

  function updatePricingRow(index: number, field: keyof PricingEntry, value: string) {
    setPricingDirty(true)
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

  function handleProfileSelectionChange(value: string) {
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
  }

  const tabDirty = tab === 'pricing' ? pricingDirty : dirty
  const pending = tab === 'pricing' ? savePricingMutation.isPending : saveMutation.isPending
  const success = tab === 'pricing' ? pricingSaved : saveMutation.isSuccess && !dirty
  const saveError = tab === 'pricing' ? savePricingMutation.error : saveMutation.error

  function handleSave() {
    if (tab === 'pricing') savePricingMutation.mutate()
    else saveMutation.mutate()
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <Tabs value={tab} onValueChange={(value) => setTab(value as SettingsTab)} className="flex flex-col h-full overflow-hidden">
        <div className="flex-shrink-0 border-b border-border/50 bg-background/80">
          <div className="mx-auto w-full max-w-4xl px-4 sm:px-8 pt-7">
            <div className="flex items-start justify-between gap-4 mb-5">
              <div className="min-w-0">
                <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
                <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                  {TAB_COPY[tab]}
                </p>
              </div>
              <div className="flex items-center gap-2.5 pt-1 shrink-0">
                {tabDirty && (
                  <span className="hidden sm:inline text-[11px] font-medium text-muted-foreground tracking-wide uppercase">
                    Unsaved
                  </span>
                )}
                {success && !tabDirty && (
                  <span className="text-success text-xs flex items-center gap-1">
                    <Check className="h-3.5 w-3.5" /> Saved
                  </span>
                )}
                {saveError != null && Boolean(saveError) && (
                  <span className="text-destructive text-xs max-w-[200px] truncate">
                    {saveError instanceof Error ? saveError.message : 'Save failed'}
                  </span>
                )}
                <Button
                  onClick={handleSave}
                  disabled={!tabDirty || pending}
                  size="sm"
                  variant={tabDirty ? 'default' : 'outline'}
                  className="h-8 px-3.5"
                >
                  {pending ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </div>

            <TabsList className="h-auto w-full justify-start gap-5 rounded-none bg-transparent p-0 -mb-px">
              <TabsTrigger value="llm" className={cn(tabTriggerClass, 'gap-1.5')}>
                LLM
                {dirty && (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-label="Unsaved LLM changes" />
                )}
              </TabsTrigger>
              <TabsTrigger value="browser" className={cn(tabTriggerClass, 'gap-1.5')}>
                Browser
                {dirty && (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-label="Unsaved browser changes" />
                )}
              </TabsTrigger>
              <TabsTrigger value="pricing" className={cn(tabTriggerClass, 'gap-1.5')}>
                Pricing
                {pricingDirty && (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-label="Unsaved pricing changes" />
                )}
              </TabsTrigger>
            </TabsList>
          </div>
        </div>

        <ScrollArea className="flex-1">
          <div className="mx-auto w-full max-w-4xl px-4 sm:px-8 py-7">
            {isLoading && (
              <p className="text-sm text-muted-foreground flex items-center gap-2 mb-6">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading…
              </p>
            )}

            <TabsContent value="llm" className="mt-0">
              <LlmSettings
                roleForms={roleForms}
                config={config}
                checkingRole={checkingRole}
                checkResults={checkResults}
                onProviderChange={handleProviderChange}
                onBaseUrlChange={(role, value) => updateRoleForm(role, { baseUrl: value })}
                onModelChange={(role, value) => updateRoleForm(role, { model: value })}
                onOpenrouterProviderChange={(role, value) =>
                  updateRoleForm(role, { openrouterProvider: value })
                }
                onApiKeyChange={(role, value) => updateRoleForm(role, { apiKey: value })}
                onApiKeyFocus={(role) => {
                  if (roleForms[role].apiKey === MASKED_API_KEY) {
                    updateRoleForm(role, { apiKey: '' })
                  }
                }}
                onApiKeyBlur={(role) => {
                  const provider = roleForms[role].provider
                  if (!roleForms[role].apiKey.trim() && isProviderApiKeySet(provider, config)) {
                    updateRoleForm(role, { apiKey: MASKED_API_KEY })
                  }
                }}
                onCheck={handleCheck}
              />
            </TabsContent>

            <TabsContent value="browser" className="mt-0">
              <BrowserSettings
                config={config}
                workerStatus={workerStatus}
                connectOnline={connectOnline}
                freshProfile={freshProfile}
                profileSelection={profileSelection}
                chromeProfiles={chromeProfiles}
                onFreshProfileChange={(value) => {
                  setDirty(true)
                  setFreshProfile(value)
                }}
                onProfileSelectionChange={handleProfileSelectionChange}
              />
            </TabsContent>

            <TabsContent value="pricing" className="mt-0">
              <PricingSettings
                pricing={pricing}
                onUpdateRow={updatePricingRow}
                onRemoveRow={(index) => {
                  setPricingDirty(true)
                  setPricing((prev) => prev.filter((_, j) => j !== index))
                }}
                onAddRow={() => {
                  setPricingDirty(true)
                  setPricing((prev) => [
                    ...prev,
                    { provider: 'groq', model: '', input: 0, output: 0, cache_read: 0 },
                  ])
                }}
              />
            </TabsContent>
          </div>
        </ScrollArea>
      </Tabs>
    </div>
  )
}
