/**
 * 品牌字体的 @font-face 装载点。
 *
 * typography.ts 里的 family 名只是字符串，不 import 这里的 CSS，字体就不存在，
 * 衬线标题会静默回退成系统宋体、正文回退成微软雅黑——不报错、不飘红，
 * 只有肉眼看得出。装载点因此单独成文件，并由 fonts.test.ts 与字体栈反向比对。
 *
 * 刻意不从 theme/index.ts 转出：那是纯副作用模块，挂进 barrel 会让所有
 * 引用主题的地方（包括单元测试）都被迫吃下字体 CSS。只由 main.tsx 拉起。
 *
 * 选包口径：
 * - 可变字体只取 wght 轴。Fraunces 另有 full / opsz / soft / wonk 等轴组合，
 *   每多一个就是一整套重复的字体文件，而设计只用到字重变化。
 * - fontsource 用 unicode-range 切分子集，浏览器只下载真正用到的那一份，
 *   所以 latin / latin-ext / vietnamese 全声明也不会多花流量。
 * - IBM Plex Mono 是静态字体，index.css 会拉进 100-700 全部字重 × 5 个子集；
 *   代码与数字只需要 400 与 500 两档 normal。
 * - CJK 一律走系统字体栈。一个中日韩 webfont 就是好几 MB，换来的是与用户
 *   本机字体几乎无差别的观感。
 */

import '@fontsource-variable/fraunces/wght.css'
import '@fontsource-variable/schibsted-grotesk/wght.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
