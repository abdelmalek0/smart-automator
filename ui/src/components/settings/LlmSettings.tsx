import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { isProviderApiKeySet } from '@/api'
import { providerUsesApiKey, UI_PROVIDERS } from '@/providers'
import type { Config } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { AGENT_ROLES, type AgentRoleId, type CheckResult, type RoleFormState } from '@/components/settings/types'
import { cn } from '@/lib/utils'

export default function LlmSettings({
  roleForms,
  config,
  checkingRole,
  checkResults,
  onProviderChange,
  onBaseUrlChange,
  onModelChange,
  onOpenrouterProviderChange,
  onApiKeyChange,
  onApiKeyFocus,
  onApiKeyBlur,
  onCheck,
}: {
  roleForms: Record<AgentRoleId, RoleFormState>
  config: Config | undefined
  checkingRole: AgentRoleId | null
  checkResults: Partial<Record<AgentRoleId, CheckResult>>
  onProviderChange: (role: AgentRoleId, value: string) => void
  onBaseUrlChange: (role: AgentRoleId, value: string) => void
  onModelChange: (role: AgentRoleId, value: string) => void
  onOpenrouterProviderChange: (role: AgentRoleId, value: string) => void
  onApiKeyChange: (role: AgentRoleId, value: string) => void
  onApiKeyFocus: (role: AgentRoleId) => void
  onApiKeyBlur: (role: AgentRoleId) => void
  onCheck: (role: AgentRoleId) => void
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {AGENT_ROLES.map((role) => (
        <LlmRoleCard
          key={role.id}
          roleId={role.id}
          title={role.title}
          description={role.description}
          form={roleForms[role.id]}
          config={config}
          checking={checkingRole === role.id}
          checkResult={checkResults[role.id]}
          onProviderChange={(value) => onProviderChange(role.id, value)}
          onBaseUrlChange={(value) => onBaseUrlChange(role.id, value)}
          onModelChange={(value) => onModelChange(role.id, value)}
          onOpenrouterProviderChange={(value) => onOpenrouterProviderChange(role.id, value)}
          onApiKeyChange={(value) => onApiKeyChange(role.id, value)}
          onApiKeyFocus={() => onApiKeyFocus(role.id)}
          onApiKeyBlur={() => onApiKeyBlur(role.id)}
          onCheck={() => onCheck(role.id)}
        />
      ))}
    </div>
  )
}

function LlmRoleCard({
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
  checkResult?: CheckResult
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
  const providerLabel =
    UI_PROVIDERS.find((item) => item.id === form.provider)?.label ?? form.provider
  const connected = checkResult?.ok === true
  const failed = checkResult && !checkResult.ok

  return (
    <section className="rounded-xl border border-border/70 bg-card/50 overflow-hidden flex flex-col">
      <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-border/50">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
          <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
          {(providerLabel || form.model) && (
            <p className="text-[11px] text-muted-foreground/80 mt-2 truncate mono">
              {[providerLabel, form.model].filter(Boolean).join(' · ')}
            </p>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className={cn(
            'h-7 px-2.5 text-xs shrink-0 max-w-[11rem] truncate',
            connected && 'text-success hover:text-success',
            failed && 'text-destructive hover:text-destructive',
          )}
          onClick={onCheck}
          disabled={checking}
        >
          {checking ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : connected ? (
            checkResult.provider_name ? `Connected · ${checkResult.provider_name}` : 'Connected'
          ) : failed ? (
            'Retry'
          ) : (
            'Test'
          )}
        </Button>
      </div>

      {failed && (
        <p className="px-5 py-2 text-xs text-destructive bg-destructive/10 border-b border-destructive/20 leading-relaxed">
          {checkResult.error ?? 'Connection failed'}
        </p>
      )}

      <div className="p-5 space-y-4 flex-1">
        <Field label="Provider">
          <Select value={form.provider} onValueChange={onProviderChange}>
            <SelectTrigger className="h-9 text-sm shadow-none">
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
        </Field>
        <Field label="Model">
          <ModelField
            key={`${roleId}-${form.provider}`}
            model={form.model}
            modelOptions={modelOptions}
            onModelChange={onModelChange}
          />
        </Field>

        <Field label="Base URL">
          <Input
            value={form.baseUrl}
            onChange={(e) => onBaseUrlChange(e.target.value)}
            className="h-9 mono text-sm shadow-none"
          />
        </Field>

        {form.provider === 'openrouter' && (
          <Field
            label="Upstream provider"
            hint="OpenRouter slug (together, deepinfra). Empty = Auto."
          >
            <Input
              value={form.openrouterProvider}
              onChange={(e) => onOpenrouterProviderChange(e.target.value)}
              placeholder="Auto"
              className="h-9 mono text-sm shadow-none"
            />
          </Field>
        )}

        {providerUsesApiKey(form.provider) && (
          <Field
            label="API key"
            extra={
              providerApiKeySet ? (
                <span className="text-[11px] text-success">Saved on server</span>
              ) : null
            }
          >
            <Input
              type="password"
              value={form.apiKey}
              onChange={(e) => onApiKeyChange(e.target.value)}
              onFocus={onApiKeyFocus}
              onBlur={onApiKeyBlur}
              autoComplete="off"
              placeholder={providerApiKeySet ? undefined : 'Enter API key…'}
              className="h-9 mono text-sm shadow-none"
            />
          </Field>
        )}
      </div>
    </section>
  )
}

function Field({
  label,
  hint,
  extra,
  children,
}: {
  label: string
  hint?: string
  extra?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <Label className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
          {label}
        </Label>
        {extra}
      </div>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground leading-relaxed">{hint}</p>}
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
      <div className="space-y-1.5">
        <Input
          ref={inputRef}
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
          className="h-9 mono text-sm shadow-none"
          placeholder="Model name"
        />
        {hasSaved && (
          <button
            type="button"
            className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            onClick={useSavedModels}
          >
            Choose from saved models
          </button>
        )}
      </div>
    )
  }

  return (
    <Select
      value={model}
      onValueChange={(value) => (value === CUSTOM ? enterCustom() : onModelChange(value))}
    >
      <SelectTrigger className="h-9 mono text-sm shadow-none">
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
  )
}
