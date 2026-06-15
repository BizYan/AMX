import { expect, test } from '@playwright/test'

import { resolveApiBaseUrl } from '../../../src/lib/api-client'

test.describe('resolveApiBaseUrl', () => {
  test('uses same-origin API path when no public API URL is configured for a remote browser', () => {
    expect(resolveApiBaseUrl('', { protocol: 'https:', hostname: 'app.avenir-matrix.internal' })).toBe('/api/v1')
  })

  test('keeps localhost fallback for local browser development when no public API URL is configured', () => {
    expect(resolveApiBaseUrl(undefined, { protocol: 'http:', hostname: 'localhost' })).toBe(
      'http://localhost:18000/api/v1',
    )
  })

  test('preserves configured non-local API URLs', () => {
    expect(
      resolveApiBaseUrl('https://api.avenir-matrix.internal/api/v1', {
        protocol: 'https:',
        hostname: 'app.avenir-matrix.internal',
      }),
    ).toBe('https://api.avenir-matrix.internal/api/v1')
  })
})
