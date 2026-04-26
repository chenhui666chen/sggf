import type { UserAssetRecord } from '@/services/api'

export type UserAssetPreviewPresentation =
  | { kind: 'placeholder'; message: string }
  | { kind: 'video'; src: string }
  | { kind: 'audio'; src: string }
  | { kind: 'image'; src: string; alt: string }

type BuildUserAssetPreviewPresentationOptions = {
  previewUrl?: string | null
  isProtectedAssetPending?: boolean
}

function readTrimmedString(value: string | null | undefined): string {
  return String(value || '').trim()
}

export function buildUserAssetPreviewPresentation(
  asset: Pick<UserAssetRecord, 'asset_kind' | 'title'>,
  options: BuildUserAssetPreviewPresentationOptions = {},
): UserAssetPreviewPresentation {
  const previewUrl = readTrimmedString(options.previewUrl)
  const title = readTrimmedString(asset.title)

  if (!previewUrl) {
    return {
      kind: 'placeholder',
      message: options.isProtectedAssetPending ? '受保护资源加载中...' : '暂无预览',
    }
  }

  if (asset.asset_kind === 'video') {
    return {
      kind: 'video',
      src: previewUrl,
    }
  }

  if (asset.asset_kind === 'audio') {
    return {
      kind: 'audio',
      src: previewUrl,
    }
  }

  return {
    kind: 'image',
    src: previewUrl,
    alt: title || '用户资产预览',
  }
}
