/**
 * i18next 的类型增强。
 *
 * 刻意**不**声明 CustomTypeOptions.resources。一旦声明，t() 的 key 会被收窄到
 * zh-CN 资源里的静态 key 集合，而全站待抽的文案中有大量 `t(\`status.${code}\`)`
 * 形式的动态 key，届时每一处都得写 cast，类型系统反而变成噪音。
 * key 的存在性改由 __tests__/namespaces.test.ts 的资源对齐测试守护——它能覆盖
 * 两种语言的 key 集合，而类型只能覆盖一种。
 */

import 'i18next'

declare module 'i18next' {
  interface CustomTypeOptions {
    /**
     * 与 namespaces.ts 的 DEFAULT_NAMESPACE 保持一致。
     * 写字面量而不写 typeof：那是 type-only 上下文，取值类型反而更脆。
     */
    defaultNS: 'common'

    /**
     * 缺 key 时返回裸 key 字符串而不是 null。
     *
     * 不声明的话 t() 的返回类型是 string | null，这个 null 会渗进每一个
     * 调用点：aria-label={t(...)} 直接类型报错，模板字符串里变成 "null"。
     * 与 client.ts 里 returnNull:false 的运行时配置必须同时成立。
     */
    returnNull: false

    /** t() 永远返回字符串；需要拿整个对象时显式用 returnObjects 选项。 */
    returnObjects: false
  }
}
