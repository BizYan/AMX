'use client'

import { useTranslations as useNextIntlTranslations } from 'next-intl'

export function useTranslation(namespace?: string) {
  const t = useNextIntlTranslations(namespace)

  return {
    t,
  }
}

export function useClientTranslation() {
  return useNextIntlTranslations()
}