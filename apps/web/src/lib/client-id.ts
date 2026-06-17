let sequenceCounter = 0

export function createClientId(prefix: string) {
  const normalizedPrefix = prefix.trim() || 'client'
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${normalizedPrefix}-${crypto.randomUUID()}`
  }

  sequenceCounter += 1
  return `${normalizedPrefix}-${sequenceCounter}`
}
