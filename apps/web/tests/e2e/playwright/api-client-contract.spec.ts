import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const repoRoot = join(__dirname, '..', '..', '..', '..', '..')

function functionBody(source: string, name: string) {
  const start = source.indexOf(`function ${name}`)
  expect(start, `${name} should exist`).toBeGreaterThanOrEqual(0)

  const nextFunction = source.indexOf('\nfunction ', start + 1)
  return source.slice(start, nextFunction === -1 ? undefined : nextFunction)
}

test('api client normalizers preserve server timestamps instead of synthesizing current time', () => {
  const source = readFileSync(join(repoRoot, 'apps/web/src/lib/api-client.ts'), 'utf8')

  for (const name of ['normalizeProject', 'normalizeSourceFile']) {
    const body = functionBody(source, name)

    expect(body, `${name} should not synthesize timestamps`).not.toContain('new Date().toISOString()')
  }
})
