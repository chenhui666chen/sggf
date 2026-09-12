import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import {
  buildUserAssetEditorDialogPresentation,
  buildUserAssetEditorFormData,
  getEmptyUserAssetEditorFormData,
  normalizeUserAssetEditorPayload,
  parseUserAssetEditorTagsInput,
} from '../user-assets/userAssetEditorPresentation'

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userAssetEditorPresentation', () => {
  it('builds and resets editor form data', () => {
    expect(
      buildUserAssetEditorFormData({
        title: '资产标题',
        description: '补充说明',
        tags: ['角色', '成片'],
      }),
    ).toEqual({
      title: '资产标题',
      description: '补充说明',
      tagsText: '角色, 成片',
    })
    expect(getEmptyUserAssetEditorFormData()).toEqual({
      title: '',
      description: '',
      tagsText: '',
    })
  })

  it('normalizes payload and validates title', () => {
    expect(
      normalizeUserAssetEditorPayload(
        {
          title: '  资产标题  ',
          description: '  描述  ',
          tagsText: '角色, 角色, 成片',
        },
        t,
      ),
    ).toEqual({
      payload: {
        title: '资产标题',
        description: '描述',
        tags: ['角色', '成片'],
      },
    })
    expect(
      normalizeUserAssetEditorPayload(
        {
          title: '   ',
          description: '',
          tagsText: '',
        },
        t,
      ),
    ).toEqual({
      validationError: '资产标题不能为空',
    })
  })

  it('parses tags and builds dialog presentation', () => {
    expect(parseUserAssetEditorTagsInput('角色，成片\n高精、角色')).toEqual([
      '角色',
      '成片',
      '高精',
    ])
    expect(
      buildUserAssetEditorDialogPresentation(
        {
          submitting: true,
          hasAsset: false,
        },
        t,
      ),
    ).toMatchObject({
      dialogTitle: '编辑资产信息',
      titleLabel: '资产标题',
      descriptionLabel: '补充说明',
      tagsLabel: '标签',
      tagsPlaceholder: '可使用逗号、中文逗号、顿号或换行分隔',
      tagsHelperText: '最多保留 12 个标签，每个标签最多 30 个字符。',
      cancelLabel: '取消',
      saveLabel: '保存',
      savingLabel: '保存中...',
      saveDisabled: true,
    })
  })
})
