import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

const browserPlayerSource = readSource('../../../components/audiobook/BrowserPlayer.tsx')
const chapterListSource = readSource('../../../components/audiobook/BrowserPlayerChapterList.tsx')
const controlsSource = readSource('../../../components/audiobook/BrowserPlayerControls.tsx')

describe('BrowserPlayer responsive layout source guards', () => {
  it('keeps the browser player usable on narrow screens', () => {
    expect(browserPlayerSource).toContain('const fullScreen = useMediaQuery(theme.breakpoints.down')
    expect(browserPlayerSource).toContain('fullScreen={fullScreen}')
    expect(browserPlayerSource).toContain("flexDirection: { xs: 'column', md: 'row' }")
    expect(browserPlayerSource).toContain("height: { xs: 'auto', md: '70vh' }")
    expect(browserPlayerSource).toContain("minHeight: { xs: 'calc(100vh - 180px)', md: 0 }")

    expect(chapterListSource).toContain("width: { xs: '100%', md: 280 }")
    expect(chapterListSource).toContain("maxHeight: { xs: 220, md: 'none' }")
    expect(chapterListSource).toContain('borderRight: { xs: 0, md: 1 }')
    expect(chapterListSource).toContain('borderBottom: { xs: 1, md: 0 }')

    expect(controlsSource).toContain('flexWrap: \'wrap\'')
    expect(controlsSource).toContain("width: { xs: '100%', sm: 'auto' }")
    expect(controlsSource).toContain("sx={{ width: { xs: '100%', sm: 100 } }}")
  })
})
