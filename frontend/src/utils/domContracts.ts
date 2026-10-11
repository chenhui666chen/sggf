/**
 * 与浏览器宿主对象打交道的最小契约。
 *
 * 项目没有 jsdom，所有 DOM / Storage 副作用都写成"接收依赖的纯函数"，
 * 靠这些窄接口注入替身。集中定义是为了避免主题、语言等模块各自声明一份
 * 同名却互不相关的结构——那样既重复，又让读者以为是同一个类型。
 */

/** 只需要写属性的元素。 */
export interface AttributeTarget {
  setAttribute(name: string, value: string): void
}

/** 只需要读取的存储。 */
export interface ReadableStorage {
  getItem(key: string): string | null
}

/** 只需要写入的存储。 */
export interface WritableStorage {
  setItem(key: string, value: string): void
}
