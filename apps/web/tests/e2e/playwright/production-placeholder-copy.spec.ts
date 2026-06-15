import { expect, test } from '@playwright/test'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'

const forbiddenExamples = [
  'https://example.com',
  'user@example.com',
  'you@company.com',
]

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = path.join(dir, entry)
    const stat = statSync(fullPath)
    if (stat.isDirectory()) return sourceFiles(fullPath)
    return /\.(tsx?|json)$/.test(entry) ? [fullPath] : []
  })
}

test('production source placeholders do not use example domains or emails', () => {
  const srcDir = path.join(process.cwd(), 'src')
  const offenders = sourceFiles(srcDir).flatMap((file) => {
    const content = readFileSync(file, 'utf8')
    return forbiddenExamples
      .filter((example) => content.includes(example))
      .map((example) => `${path.relative(process.cwd(), file)} contains ${example}`)
  })

  expect(offenders).toEqual([])
})
