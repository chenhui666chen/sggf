/**
 * 命名空间注册表的契约。
 *
 * 注册表是"加一门语言 / 加一个命名空间"的唯一入口。它一旦和真实资源目录脱节，
 * 症状是界面上渲染出裸 key（common.action.save）而不是抛错——没有堆栈、
 * 没有红屏，只有用户看见一串英文句点。所以这里把结构约束和真实加载能力一起钉住。
 */
import { describe, expect, it } from 'vitest'

import { DEFAULT_LANGUAGE, SUPPORTED_LANGUAGE_CODES } from '../language'
import { DEFAULT_NAMESPACE, NAMESPACES, NAMESPACE_NAMES, loadNamespace } from '../namespaces'
import enCommon from '../resources/en-US/common.json'
import zhCommon from '../resources/zh-CN/common.json'
import type { NamespaceEntry } from '../namespaces'

const commonEntry = NAMESPACES.find((entry) => entry.name === 'common') as NamespaceEntry

describe('namespace registry', () => {
  it('registers common as the default namespace', () => {
    expect(DEFAULT_NAMESPACE).toBe('common')
    expect(NAMESPACE_NAMES).toContain(DEFAULT_NAMESPACE)
  })

  it('derives NAMESPACE_NAMES from NAMESPACES so the two cannot drift', () => {
    expect(NAMESPACE_NAMES).toEqual(NAMESPACES.map((entry) => entry.name))
  })

  it('lists every namespace exactly once', () => {
    expect(new Set(NAMESPACE_NAMES).size).toBe(NAMESPACE_NAMES.length)
  })

  it('gives every namespace a non-empty inlined source bundle', () => {
    for (const entry of NAMESPACES) {
      expect(Object.keys(entry.source).length, entry.name).toBeGreaterThan(0)
    }
  })

  it('never registers a lazy loader for the source language', () => {
    // 事实源语言必须内联：它是"首帧 t() 就能出中文、永不裸 key"的唯一保证。
    for (const entry of NAMESPACES) {
      expect(Object.keys(entry.loaders), entry.name).not.toContain(DEFAULT_LANGUAGE)
    }
  })

  it('only registers loaders for supported languages', () => {
    for (const entry of NAMESPACES) {
      for (const code of Object.keys(entry.loaders)) {
        expect(SUPPORTED_LANGUAGE_CODES, `${entry.name}/${code}`).toContain(code)
      }
    }
  })

  it('ships a loader for every non-source language', () => {
    // 漏一个 loader 不会报错，只会让那门语言静默退回中文，比崩掉更难发现。
    for (const entry of NAMESPACES) {
      for (const code of SUPPORTED_LANGUAGE_CODES) {
        if (code === DEFAULT_LANGUAGE) {
          continue
        }
        expect(entry.loaders[code], `${entry.name}/${code}`).toBeTypeOf('function')
      }
    }
  })
})

describe('loadNamespace', () => {
  it('returns the inlined bundle for the source language without touching loaders', async () => {
    // 用 toBe 而非 toEqual：必须拿到同一个引用，证明没有走任何异步加载。
    await expect(loadNamespace(commonEntry, DEFAULT_LANGUAGE)).resolves.toBe(commonEntry.source)
  })

  it('resolves the lazy bundle for a translated language', async () => {
    await expect(loadNamespace(commonEntry, 'en-US')).resolves.toEqual(enCommon)
  })

  it('unwraps the dynamic import so callers never see a module namespace', async () => {
    // Vite 的 import('./x.json') 返回 { default: ... }；不解包的话
    // addResourceBundle 会把整层 default 当成资源，所有 key 都多一级前缀。
    const bundle = await loadNamespace(commonEntry, 'en-US')

    expect(bundle).not.toHaveProperty('default')
    expect(bundle?.app).toBeDefined()
  })

  it('returns null when a language has no loader registered', async () => {
    const untranslated: NamespaceEntry = { name: 'bare', source: { a: 1 }, loaders: {} }

    await expect(loadNamespace(untranslated, 'en-US')).resolves.toBeNull()
  })

  it('surfaces a loader failure instead of swallowing it', async () => {
    // 吞掉异常会让"chunk 404"退化成静默显示中文，排查时无从下手。
    // 降级与否由调用方（切语言流程）决定，这里只负责把错误传上去。
    const broken: NamespaceEntry = {
      name: 'broken',
      source: { a: 1 },
      loaders: { 'en-US': () => Promise.reject(new Error('chunk missing')) },
    }

    await expect(loadNamespace(broken, 'en-US')).rejects.toThrow('chunk missing')
  })
})

describe('brand name', () => {
  it('names the product 拾光工坊 in Chinese', () => {
    expect(zhCommon.app.name).toBe('拾光工坊')
  })

  it('names the product Shiguang Studio in English', () => {
    // 旧名 Novel Writing Agent 只覆盖小说场景，产品实际已含图片/视频/音频/短剧。
    expect(enCommon.app.name).toBe('Shiguang Studio')
  })

  it('keeps both bundles structurally aligned so no key resolves only in one language', () => {
    expect(Object.keys(enCommon).sort()).toEqual(Object.keys(zhCommon).sort())
  })
})
