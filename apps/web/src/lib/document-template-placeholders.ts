import type { Document } from './api-client'

function documentMetadata(document: Document) {
  return {
    ...(document.metadata_json || {}),
    ...(document.metadata || {}),
  }
}

function normalizePlaceholder(value: unknown) {
  if (typeof value !== 'string') return null
  const normalized = value.trim().replace(/^\{\{\s*/, '').replace(/\s*\}\}$/, '')
  return normalized || null
}

function collectPlaceholderValues(input: unknown) {
  if (!Array.isArray(input)) return []
  return input.map(normalizePlaceholder).filter((value): value is string => Boolean(value))
}

export function getUnresolvedTemplatePlaceholders(document: Document) {
  const metadata = documentMetadata(document)
  const evidence = metadata.template_placeholder_evidence || {}
  const values = [
    ...collectPlaceholderValues(metadata.unresolved_template_placeholders),
    ...collectPlaceholderValues(evidence.unresolved_placeholders),
    ...collectPlaceholderValues(evidence.unresolved),
  ]
  return Array.from(new Set(values))
}

export function hasUnresolvedTemplatePlaceholders(document: Document) {
  return getUnresolvedTemplatePlaceholders(document).length > 0
}

export function templatePlaceholderSummary(document: Document) {
  return getUnresolvedTemplatePlaceholders(document).join('、')
}

export function hasTemplatePlaceholderBlocker(document: Document) {
  const metadata = documentMetadata(document)
  return (
    document.status === 'placeholder' ||
    metadata.status === 'placeholder' ||
    metadata.has_placeholders === true ||
    metadata.generation_status === 'placeholder' ||
    hasUnresolvedTemplatePlaceholders(document)
  )
}
