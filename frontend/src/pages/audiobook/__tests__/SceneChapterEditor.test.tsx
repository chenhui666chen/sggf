import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { renderToStaticMarkup } from 'react-dom/server'

import SceneChapterEditor, {
  EDIT_TYPE_LABELS,
  SCENE_STATUS_LABELS,
} from '../SceneChapterEditor'

const componentSource = readFileSync(
  fileURLToPath(new URL('../SceneChapterEditor.tsx', import.meta.url)),
  'utf-8',
)

function visibleText(markup: string): string {
  return markup
    .replace(/<style[^>]*>[\s\S]*?<\/style>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&gt;/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('SceneChapterEditor', () => {
  it('renders the editor dialog title with chapter and batch context', () => {
    const markup = renderToStaticMarkup(
      <SceneChapterEditor
        open
        chapterId={3}
        audiobookProjectId={42}
        engineMode="seed_scene"
        renderStatus="rendered_all_seed"
        batches={[
          { id: 42, engine_mode: 'seed_scene', created_at: '2026-08-15T00:00:00Z' },
          { id: 43, engine_mode: 'seed_scene', created_at: '2026-08-14T00:00:00Z' },
        ]}
        disablePortal
        onClose={() => undefined}
      />,
    )
    const text = visibleText(markup)
    expect(text).toContain('场景编辑器')
    expect(text).toContain('第 3 章')
    expect(text).toContain('rendered_all_seed')
    expect(text).toContain('#42')
  })

  it('prefers chapterNumber over chapterId in the dialog title', () => {
    const markup = renderToStaticMarkup(
      <SceneChapterEditor
        open
        chapterId={58}
        chapterNumber={1}
        audiobookProjectId={61}
        engineMode="seed_scene"
        renderStatus={null}
        disablePortal
        onClose={() => undefined}
      />,
    )
    const text = visibleText(markup)
    expect(text).toContain('场景编辑器 · 第 1 章')
    expect(text).not.toContain('第 58 章')
  })

  it('maps scene render statuses to labels and colors', () => {
    expect(SCENE_STATUS_LABELS.passed.label).toBe('已通过')
    expect(SCENE_STATUS_LABELS.passed.color).toBe('success')
    expect(SCENE_STATUS_LABELS.manual_review.label).toBe('人工评审')
    expect(SCENE_STATUS_LABELS.manual_review.color).toBe('warning')
    expect(SCENE_STATUS_LABELS.legacy_stems.label).toBe('回退素材')
    expect(SCENE_STATUS_LABELS.stale.label).toBe('已过期')
    expect(SCENE_STATUS_LABELS.failed.color).toBe('error')
  })

  it('covers the three edit types with Chinese labels', () => {
    expect(EDIT_TYPE_LABELS).toEqual({
      dialogue: '台词编辑',
      director_override: '导演覆盖',
      voice_binding: '音色编辑',
    })
  })

  it('sends base_revision_hash per edit type and handles 409 conflicts', () => {
    // §3.5：保存携带 base_revision_hash（来自 last_revisions[?edit_type]）；
    // 409 Conflict 提示“文档已被他人修改，请刷新后重试”
    expect(componentSource).toContain('base_revision_hash: baseRevisionHash(')
    expect(componentSource).toContain('文档已被他人修改，请刷新后重试')
    expect(componentSource).toContain('updateSceneEditorDocument(')
    expect(componentSource).toContain("'dialogue'")
    expect(componentSource).toContain("'director_override'")
    expect(componentSource).toContain("'voice_binding'")
    // 台词编辑走 script_json（不删除 checkpoint）；导演覆盖不修改原文
    expect(componentSource).toContain('指令内容（不修改原文）')
  })

  it('offers in-editor script approval via dialogue-review before rerender', () => {
    // §2.9 审批闭环：场景编辑器内置批准入口（dialogue-review 直批），
    // 避免走旧 PUT /script 接口被 409 拒绝
    expect(componentSource).toContain('reviewSceneDialogue(')
    expect(componentSource).toContain("verdict: 'approved'")
    expect(componentSource).toContain('批准剧本')
  })

  it('surfaces the scene prompt and per-segment sound design form (P1 透明化)', () => {
    // P1：渲染提示词对用户可见可对照；台词编辑升级为细编表单
    // （环境/表演/音效/配乐），保存后由后端转译进渲染提示词
    expect(componentSource).toContain('渲染提示词')
    expect(componentSource).toContain('重新编译')
    expect(componentSource).toContain('applySegmentDetailDraft')
    expect(componentSource).toContain('segmentSoundEffectsDraftValue')
    expect(componentSource).toContain('segmentMusicCueDraftValue')
    expect(componentSource).toContain('场景环境')
    expect(componentSource).toContain('表演指导')
    expect(componentSource).toContain('伴随音效')
    expect(componentSource).toContain('配乐')
  })

  it('explains director override types in Chinese and form-izes voice binding (P2)', () => {
    // P2：覆盖类型中文说明、已生效覆盖回显；音色 JSON 手写改角色表单
    expect(componentSource).toContain('DIRECTION_TYPE_LABELS')
    expect(componentSource).toContain('DIRECTION_TYPE_HINTS')
    expect(componentSource).toContain('声学环境')
    expect(componentSource).toContain('serializeVoiceCharacters')
    expect(componentSource).toContain('角色名')
    expect(componentSource).toContain('音色 ID')
    expect(componentSource).not.toContain('characters（JSON 数组）')
  })

  it('echoes current voice binding and offers selectable voice pool presets', () => {
    // 音色编辑不再让用户裸写音色 ID：回显当前生效绑定，
    // 音色从音色库（私有复刻/设计 + 公共音色池）下拉选择，
    // 并按后端 voice_reference_resolver 白名单标记不兼容项
    expect(componentSource).toContain('voice_binding_current')
    expect(componentSource).toContain('voiceBindingDraftFromEcho')
    expect(componentSource).toContain('useAudiobookSceneVoicePool')
    expect(componentSource).toContain('markSeedSceneIncompatibleVoicePresets')
    expect(componentSource).toContain('Autocomplete')
    // reference_source 仅接受后端白名单值，旧占位符会误导用户
    expect(componentSource).not.toContain('voice_pool / clone')
  })

  it('offers scene preview via scene_audio_url and batch switcher', () => {
    // §3.5：试听按钮使用 scene_audio_url（playExternalUrl 复用）；批次切换器（§2.5 规则 3）
    expect(componentSource).toContain('scene.scene_audio_url')
    expect(componentSource).toContain('playExternalUrl')
    expect(componentSource).toContain('ToggleButtonGroup')
    expect(componentSource).toContain('批次切换')
    expect(componentSource).toContain('试听整章')
  })
})
