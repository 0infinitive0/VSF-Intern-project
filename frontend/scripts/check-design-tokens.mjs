#!/usr/bin/env node
/**
 * check-design-tokens.mjs — Layer-1 token gate (see phase-01 doc, §Nguồn token).
 *
 * The design token values have ONE origin: three CSS files copied byte-for-byte from
 * data/trip_planner/trip_planner_components/styles/ into frontend/src/styles/. This
 * script enforces that origin has no drift:
 *
 *   1. Byte-diff each copied file against its design source. Any difference => fail
 *      with a unified diff. There is no exception list by design: a copied file that
 *      was edited is wrong by definition. To change a token value, edit the design
 *      source and re-copy.
 *
 *   2. Every `var(--xxx)` referenced inside the `@theme inline { ... }` block in
 *      styles.css must actually exist in design-variables.css. An alias pointing at a
 *      nonexistent token is a silent failure — the resulting utility is empty and
 *      nothing reports it.
 *
 * Pure Node, zero dependencies. Gate: `npm run check:tokens`.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const here = dirname(fileURLToPath(import.meta.url))
const srcStyles = join(here, '..', 'src', 'styles')
const stylesCss = join(here, '..', 'src', 'styles.css')

const pairs = [
  ['design-variables.css', 'trip_planner_components/styles/variables.css'],
  ['design-theme.css', 'trip_planner_components/styles/theme.css'],
  ['design-animation.css', 'trip_planner_components/styles/animation.css'],
]

const repoRoot = join(here, '..', '..')
const designBase = join(repoRoot, 'data', 'trip_planner', 'trip_planner_components', 'styles')

let failures = []

// --- 1. byte-diff the three copied files -------------------------------------
for (const [copiedName, sourceRel] of pairs) {
  const copiedPath = join(srcStyles, copiedName)
  const sourcePath = join(designBase, copiedName === 'design-variables.css' ? 'variables.css'
    : copiedName === 'design-theme.css' ? 'theme.css'
    : 'animation.css')

  let same = false
  try {
    execFileSync('diff', ['-q', sourcePath, copiedPath], { stdio: 'pipe' })
    same = true
  } catch {
    same = false
  }
  if (!same) {
    failures.push(`\n✗ ${copiedName} differs from design source ${sourceRel}`)
    try {
      const diffOut = execFileSync('diff', ['-u', sourcePath, copiedPath], { encoding: 'utf8' })
      failures.push(diffOut)
    } catch (err) {
      failures.push(String(err.stdout ?? ''))
    }
  } else {
    console.log(`✓ ${copiedName} byte-identical to ${sourceRel}`)
  }
}

// --- 2. every var(--x) in @theme inline must exist in design-variables.css -----
const cssText = readFileSync(stylesCss, 'utf8')
const inlineBlock = cssText.match(/@theme\s+inline\s*\{([\s\S]*?)\}/)
const variablesText = readFileSync(join(srcStyles, 'design-variables.css'), 'utf8')
const definedNames = new Set(
  [...variablesText.matchAll(/--([a-zA-Z0-9-]+)\s*:/g)].map((m) => m[1]),
)

if (!inlineBlock) {
  failures.push('\n✗ No `@theme inline { ... }` block found in styles.css — the alias layer is missing.')
} else {
  const refs = [...inlineBlock[1].matchAll(/var\(--([a-zA-Z0-9-]+)\)/g)].map((m) => m[1])
  const missing = [...new Set(refs)].filter((name) => !definedNames.has(name))
  if (missing.length) {
    failures.push(`\n✗ @theme inline references token(s) not defined in design-variables.css: ${missing.join(', ')}`)
  } else {
    console.log(`✓ all ${new Set(refs).size} var(--*) refs in @theme inline resolve in design-variables.css`)
  }
}

if (failures.length) {
  console.error(failures.join(''))
  process.exit(1)
}
console.log('check:tokens — passed')