import createMiddleware from 'next-intl/middleware'
import { locales, defaultLocale } from './i18n'

export default createMiddleware({
  locales,
  defaultLocale,
  localePrefix: 'as-needed',
})

export const config = {
  matcher: ['/(zh-CN|en-US)/:path*'],
}
