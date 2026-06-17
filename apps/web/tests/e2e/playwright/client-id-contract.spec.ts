import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const repoRoot = join(__dirname, '..', '..', '..', '..', '..')

const clientIdConsumers = [
  'src/app/(app)/projects/[projectId]/files/page.tsx',
  'src/app/(app)/exports/page.tsx',
  'src/components/ui/toast.tsx',
]

test('client-local UI identifiers use the shared UUID helper', () => {
  for (const relativePath of clientIdConsumers) {
    const source = readFileSync(join(repoRoot, 'apps/web', relativePath), 'utf8')

    expect(source, `${relativePath} should import the shared helper`).toContain('createClientId')
    expect(source, `${relativePath} should not use clock-based IDs`).not.toContain('Date.now()')
    expect(source, `${relativePath} should not use random decimal IDs`).not.toContain('Math.random()')
  }
})
