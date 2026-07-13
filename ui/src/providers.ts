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
  return 'ollama-cloud'
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
  if (canonical === 'ollama') return 'qwen3:14b'
  return 'gemma4:31b-cloud'
}
