type AudiobookPageModule = typeof import('../AudiobookPage')

let audiobookPageModulePromise: Promise<AudiobookPageModule> | null = null

export const loadAudiobookPageModule = (): Promise<AudiobookPageModule> => {
  if (!audiobookPageModulePromise) {
    audiobookPageModulePromise = import('../AudiobookPage')
  }

  return audiobookPageModulePromise
}

export const preloadAudiobookPage = (): void => {
  void loadAudiobookPageModule()
}
