/** Canonical LLM provider ids shared by settings UI. */
export type LlmProvider = 'groq' | 'ollama-cloud' | 'ollama' | 'google'

const PROVIDER_ALIASES: Record<string, LlmProvider> = {
  'ollama-local': 'ollama',
  ollama_local: 'ollama',
  local: 'ollama',
  gemini: 'google',
  'google-gemini': 'google',
  google_gemini: 'google',
}

export function normalizeProvider(provider: string): LlmProvider {
  const key = provider.trim().toLowerCase()
  if (key in PROVIDER_ALIASES) return PROVIDER_ALIASES[key]
  if (key === 'groq' || key === 'ollama-cloud' || key === 'ollama' || key === 'google') {
    return key
  }
  return 'groq'
}

export function isOllamaCloudUrl(baseUrl: string): boolean {
  return baseUrl.trim().toLowerCase().includes('ollama.com')
}

export function isValidBaseUrlForProvider(provider: string, baseUrl: string): boolean {
  const canonical = normalizeProvider(provider)
  const url = baseUrl.trim()
  if (!url) return false
  if (canonical === 'ollama') return !isOllamaCloudUrl(url)
  if (canonical === 'ollama-cloud') return isOllamaCloudUrl(url)
  return true
}

export function providerUsesApiKey(provider: string): boolean {
  const canonical = normalizeProvider(provider)
  return canonical !== 'ollama'
}

export function defaultBaseUrl(provider: string): string {
  const canonical = normalizeProvider(provider)
  if (canonical === 'groq') return 'https://api.groq.com/openai/v1'
  if (canonical === 'google') {
    return 'https://generativelanguage.googleapis.com/v1beta/openai'
  }
  if (canonical === 'ollama') return 'http://localhost:11434'
  return 'https://ollama.com'
}

export function defaultModel(provider: string): string {
  const canonical = normalizeProvider(provider)
  if (canonical === 'groq') return 'llama-3.3-70b-versatile'
  if (canonical === 'google') return 'gemini-2.5-flash'
  if (canonical === 'ollama') return 'llama3.2'
  return 'gemma4:31b-cloud'
}
