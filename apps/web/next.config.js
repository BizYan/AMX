const withNextIntl = require('next-intl/plugin')('./src/i18n/request.ts')

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  ...(process.platform === 'win32' ? {} : { output: 'standalone' }),
  serverExternalPackages: ['elkjs'],
}

module.exports = withNextIntl(nextConfig)
