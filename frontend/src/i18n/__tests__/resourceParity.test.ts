/**
 * 双语资源对齐契约：叶子键位 + 插值占位符。
 *
 * fallbackLng 链里恒含 zh-CN（client.test.ts 钉住了这一点），因此 en-US 缺一个
 * 叶子键的症状既不是裸 key 也不是空白，而是英文界面里静默冒出一句中文——
 * 不报错、没堆栈、在代码库里也搜不到。namespaces.test.ts 只比对顶层组名，抓不到
 * 缺叶子，所以这里把两份 bundle 拍平到叶子路径再双向对齐，缺谁点名谁。
 *
 * 占位符单独查一遍：{{mode}} 这类插值若在译文里丢了，键位依然是齐的，但文案会
 * 退化成静态串（aria-label 读不出当前是浅色还是深色），只有逐键比对才抓得到。
 *
 * 遍历 NAMESPACES 全体而不是只 common：注册表是「加一门语言 / 加一个命名空间」
 * 的唯一入口，守护长在入口上，新登记的命名空间才会自动被覆盖。
 */
import { describe, expect, it } from 'vitest'

import { DEFAULT_LANGUAGE, SUPPORTED_LANGUAGE_CODES } from '../language'
import { loadNamespace, NAMESPACES } from '../namespaces'
import type { AppLanguage } from '../language'
import type { NamespaceEntry, ResourceBundle } from '../namespaces'

/** i18next 的插值语法，两侧空白允许：{{ mode }} 与 {{mode}} 等价。 */
const PLACEHOLDER = /\{\{\s*([\w.]+)\s*\}\}/g

/**
 * 拍平成叶子路径。空对象不产出任何路径——它在一门语言里是组、在另一门里是叶子时，
 * 两边的路径集合自然不等，而那正是要报出来的漂移。
 */
function collectLeafPaths(node: unknown, prefix = '', out: string[] = []): string[] {
  if (typeof node === 'object' && node !== null && !Array.isArray(node)) {
    for (const [key, value] of Object.entries(node as ResourceBundle)) {
      collectLeafPaths(value, prefix ? `${prefix}.${key}` : key, out)
    }

    return out
  }

  out.push(prefix)

  return out
}

function readByPath(bundle: ResourceBundle, leafPath: string): unknown {
  return leafPath.split('.').reduce<unknown>((node, key) => {
    if (typeof node === 'object' && node !== null) {
      return (node as ResourceBundle)[key]
    }

    return undefined
  }, bundle)
}

/** 只取字符串值的占位符；数字、布尔一类不参与插值，没有可比的东西。 */
function placeholdersOf(value: unknown): string[] {
  if (typeof value !== 'string') {
    return []
  }

  return [...value.matchAll(PLACEHOLDER)].map((match) => match[1]).sort()
}

/**
 * 事实源之外、且确实登记了 loader 的语言。「登记了却没有 loader」那种缺失由
 * namespaces.test.ts 负责，这里只管两边都有资源时内容对不对得上。
 */
function translatedLanguagesOf(entry: NamespaceEntry): AppLanguage[] {
  return SUPPORTED_LANGUAGE_CODES.filter(
    (code) => code !== DEFAULT_LANGUAGE && entry.loaders[code] !== undefined,
  )
}

describe('resource parity', () => {
  it('gives every namespace the same leaf keys in every translated language', async () => {
    for (const entry of NAMESPACES) {
      const sourceLeaves = collectLeafPaths(entry.source).sort()

      for (const code of translatedLanguagesOf(entry)) {
        const bundle = await loadNamespace(entry, code)
        const leaves = collectLeafPaths(bundle ?? {}).sort()
        const at = `${entry.name}/${code}`

        // 双向点名：只报「缺了哪些」会让人以为多出来的那些是无害的。
        expect(
          sourceLeaves.filter((leaf) => !leaves.includes(leaf)),
          `${at} 缺失的叶子键，这些键会在该语言下静默退回中文`,
        ).toEqual([])
        expect(
          leaves.filter((leaf) => !sourceLeaves.includes(leaf)),
          `${at} 多出的叶子键，事实源里没有，永远不会被任何 t() 用到`,
        ).toEqual([])
      }
    }
  })

  it('keeps every interpolation placeholder the source language uses', async () => {
    for (const entry of NAMESPACES) {
      for (const code of translatedLanguagesOf(entry)) {
        const bundle = await loadNamespace(entry, code)

        if (!bundle) {
          continue
        }

        for (const leaf of collectLeafPaths(entry.source)) {
          const expected = placeholdersOf(readByPath(entry.source, leaf))

          if (expected.length === 0) {
            continue
          }

          expect(
            placeholdersOf(readByPath(bundle, leaf)),
            `${entry.name}/${code} 的 ${leaf} 占位符与事实源不一致`,
          ).toEqual(expected)
        }
      }
    }
  })
})
