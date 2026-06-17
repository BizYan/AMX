let fallbackSequence = 0

export function createClientId(prefix: string) {
  const normalizedPrefix = prefix.trim() || 'client'
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${normalizedPrefix}-${crypto.randomUUID()}`
  }

  fallbackSequence += 1
  return `${normalizedPrefix}-${fallbackSequence}`
}
