/** Canonical LLM provider ids selectable in Settings. */
export type LlmProvider = 'groq' | 'ollama-cloud' | 'google' | 'openrouter'

/** Legacy / CLI ids that normalize may still return. */
type LegacyLlmProvider = LlmProvider | 'ollama'

export const UI_PROVIDERS: { id: LlmProvider; label: string }[] = [
  { id: 'ollama-cloud', label: 'Ollama Cloud' },
  { id: 'google', label: 'Google Gemini' },
  { id: 'openrouter', label: 'OpenRouter' },
  { id: 'groq', label: 'Groq' },
]

const PROVIDER_ALIASES: Record<string, LegacyLlmProvider> = {
  'ollama-local': 'ollama',
  ollama_local: 'ollama',
  local: 'ollama',
  gemini: 'google',
  'google-gemini': 'google',
  google_gemini: 'google',
}

export function normalizeProvider(provider: string): LegacyLlmProvider {
  const key = provider.trim().toLowerCase()
  if (key in PROVIDER_ALIASES) return PROVIDER_ALIASES[key]
  if (
    key === 'groq' ||
    key === 'ollama-cloud' ||
    key === 'ollama' ||
    key === 'google' ||
    key === 'openrouter'
  ) {
    return key
  }
  return 'groq'
}

/** Map any provider id to one shown in Settings. */
export function coerceUiProvider(provider: string): LlmProvider {
  const canonical = normalizeProvider(provider)
  if (canonical === 'ollama') return 'groq'
  return canonical
}

export function isOllamaCloudUrl(baseUrl: string): boolean {
  return baseUrl.trim().toLowerCase().includes('ollama.com')
}

export function isValidBaseUrlForProvider(provider: string, baseUrl: string): boolean {
  const canonical = coerceUiProvider(provider)
  const url = baseUrl.trim()
  if (!url) return false
  if (canonical === 'ollama-cloud') return isOllamaCloudUrl(url)
  return true
}

export function providerUsesApiKey(provider: string): boolean {
  return true
}

export function defaultBaseUrl(provider: string): string {
  const canonical = coerceUiProvider(provider)
  if (canonical === 'groq') return 'https://api.groq.com/openai/v1'
  if (canonical === 'google') {
    return 'https://generativelanguage.googleapis.com/v1beta/openai'
  }
  if (canonical === 'openrouter') return 'https://openrouter.ai/api/v1'
  return 'https://ollama.com'
}

export function defaultModel(provider: string): string {
  const canonical = coerceUiProvider(provider)
  if (canonical === 'groq') return 'llama-3.3-70b-versatile'
  if (canonical === 'google') return 'gemini-2.5-flash'
  if (canonical === 'openrouter') return 'deepseek/deepseek-v4-flash-0731'
  return 'gemma4:31b-cloud'
}
