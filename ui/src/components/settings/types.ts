export const PROFILE_APP_DEFAULT = '__app_default__'
export const PROFILE_CUSTOM = '__custom__'
/** Display-only stand-in when a key is stored; never sent to the server. */
export const MASKED_API_KEY = '********'

export const AGENT_ROLES = [
  {
    id: 'planning' as const,
    title: 'Planning',
    description: 'Planner, actor-critic, and HITL debrief',
  },
  {
    id: 'navigation' as const,
    title: 'Navigation',
    description: 'Navigator and criteria checker',
  },
]

export type AgentRoleId = (typeof AGENT_ROLES)[number]['id']

export type RoleFormState = {
  provider: string
  baseUrl: string
  model: string
  apiKey: string
  openrouterProvider: string
}

export type CheckResult = { ok: boolean; error?: string; provider_name?: string }
