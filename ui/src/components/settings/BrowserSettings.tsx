import ConnectOfflineNotice from '@/components/ConnectOfflineNotice'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import SettingsRow from '@/components/settings/SettingsRow'
import { PROFILE_APP_DEFAULT } from '@/components/settings/types'
import type { BrowserSessionMode, ChromeProfile, Config, WorkerStatus } from '@/types'
import { cn } from '@/lib/utils'

export default function BrowserSettings({
  config,
  workerStatus,
  connectOnline,
  freshProfile,
  profileSelection,
  chromeProfiles,
  onFreshProfileChange,
  onProfileSelectionChange,
}: {
  config: Config | undefined
  workerStatus: WorkerStatus | undefined
  connectOnline: boolean
  freshProfile: boolean
  profileSelection: string
  chromeProfiles: ChromeProfile[]
  onFreshProfileChange: (value: boolean) => void
  onProfileSelectionChange: (value: string) => void
}) {
  const browserState =
    connectOnline && workerStatus?.browser_state && workerStatus.browser_state !== 'idle'
      ? workerStatus.browser_state
      : null

  const activeProfile =
    config?.effective_chrome_profile
    || (config?.browser_session_mode === 'ephemeral'
      ? 'Fresh profile (discarded after each run)'
      : config?.effective_chrome_user_data
        || '—')

  const profileHint = freshProfile
    ? 'Disabled while fresh profile is on — each run starts with a blank browser.'
    : !connectOnline
      ? 'Profiles appear when Connect is online.'
      : chromeProfiles.length === 0
        ? 'No system profiles advertised yet — Connect will use the app default.'
        : profileSelection === PROFILE_APP_DEFAULT
          ? 'Uses the Connect app default. Cookies and history persist between runs.'
          : 'System profiles are mirrored on the Connect machine before launch.'

  return (
    <div className="space-y-4">
      {!connectOnline && (
        <ConnectOfflineNotice message="Connect is offline. Runs will fail until the Connect app is logged in and connected." />
      )}

      <section className="rounded-xl border border-border/70 bg-card/50 overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-border/50">
          <div>
            <h3 className="text-sm font-semibold tracking-tight">Connect</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Chrome runs on the Connect machine — this server never launches it.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
                connectOnline
                  ? 'border-success/30 bg-success/10 text-success'
                  : 'border-warning/30 bg-warning/10 text-warning',
              )}
            >
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  connectOnline ? 'bg-success' : 'bg-warning',
                )}
                aria-hidden
              />
              {connectOnline ? 'Online' : 'Offline'}
            </span>
            {browserState && (
              <span className="text-xs text-muted-foreground capitalize">{browserState}</span>
            )}
          </div>
        </div>

        <div className="px-5 py-2">
          <SettingsRow
            label="Fresh profile"
            hint="Discard all browser state after each run. On by default."
            htmlFor="fresh-profile"
          >
            <Switch
              id="fresh-profile"
              checked={freshProfile}
              onCheckedChange={onFreshProfileChange}
            />
          </SettingsRow>

          <SettingsRow
            label="Chrome profile"
            hint={profileHint}
            htmlFor="chrome-profile-select"
          >
            <Select
              value={profileSelection}
              onValueChange={onProfileSelectionChange}
              disabled={freshProfile}
            >
              <SelectTrigger id="chrome-profile-select" className="h-9 text-sm shadow-none max-w-md">
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
          </SettingsRow>
        </div>

        {config && (
          <div className="px-5 py-3 border-t border-border/40 bg-muted/20">
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {sessionModeLabel(config.browser_session_mode)}
              {' · '}
              {activeProfile}
            </p>
          </div>
        )}
      </section>
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
