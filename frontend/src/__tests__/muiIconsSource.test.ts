import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const srcRoot = fileURLToPath(new URL('..', import.meta.url))
const projectRoot = fileURLToPath(new URL('../../', import.meta.url))
const viteConfigPath = fileURLToPath(new URL('../../vite.config.ts', import.meta.url))

const collectSourceFiles = (directory: string): string[] => {
  const entries = readdirSync(directory, { withFileTypes: true })

  return entries.flatMap((entry) => {
    const entryPath = path.join(directory, entry.name)

    if (entry.isDirectory()) {
      return collectSourceFiles(entryPath)
    }

    if (statSync(entryPath).isFile() && /\.(ts|tsx)$/.test(entry.name)) {
      return [entryPath]
    }

    return []
  })
}

describe('MUI icons source contract', () => {
  it('avoids barrel imports from @mui/icons-material in frontend source files', () => {
    const offenders = collectSourceFiles(srcRoot)
      .filter((filePath) => /from\s+['"]@mui\/icons-material['"]/.test(readFileSync(filePath, 'utf8')))
      .map((filePath) => path.relative(projectRoot, filePath))

    expect(offenders).toEqual([])
  })

  it('lets Vite resolve @mui/icons-material without the esm barrel alias or optimizeDeps exclude', () => {
    const viteConfigSource = readFileSync(viteConfigPath, 'utf8')
    const optimizeDepsExcludeBlock = viteConfigSource.match(/exclude:\s*\[([\s\S]*?)\]/)?.[1] ?? ''

    expect(viteConfigSource).not.toMatch(
      /['"]@mui\/icons-material['"]\s*:\s*path\.resolve\(__dirname,\s*['"]\.\/node_modules\/@mui\/icons-material\/esm['"]\)/,
    )
    expect(optimizeDepsExcludeBlock).not.toContain("'@mui/icons-material'")
    expect(optimizeDepsExcludeBlock).not.toContain('"@mui/icons-material"')
  })

  it('does not hard-code the HMR websocket port', () => {
    const viteConfigSource = readFileSync(viteConfigPath, 'utf8')

    expect(viteConfigSource).not.toMatch(/hmr:\s*\{[\s\S]*port:\s*5173[\s\S]*\}/)
  })
})
