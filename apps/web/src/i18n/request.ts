import { getRequestConfig } from 'next-intl/server'
import { notFound } from 'next/navigation'

export const locales = ['zh-CN', 'en-US'] as const
export type Locale = (typeof locales)[number]

export const defaultLocale: Locale = 'zh-CN'

export default getRequestConfig(async ({ locale }) => {
  const resolvedLocale = locale ?? defaultLocale

  if (!locales.includes(resolvedLocale as Locale)) {
    notFound()
  }

  return {
    locale: resolvedLocale,
    messages: (await import(`../messages/${resolvedLocale}.json`)).default,
  }
})