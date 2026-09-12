import type { TFunction } from 'i18next'
import type { UserAssetRecord } from '@/services/api'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

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
  t?: TFunction,
): UserAssetPreviewPresentation {
  const translate = t ?? DEFAULT_TRANSLATE
  const previewUrl = readTrimmedString(options.previewUrl)
  const title = readTrimmedString(asset.title)

  if (!previewUrl) {
    return {
      kind: 'placeholder',
      message: options.isProtectedAssetPending
        ? translate('userAsset.preview.protectedLoading')
        : translate('userAsset.preview.noPreview'),
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
    alt: title || translate('userAsset.preview.assetPreview'),
  }
}
