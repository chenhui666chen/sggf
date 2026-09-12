/**
 * P2-5.2：同意条款版本常量。
 *
 * 必须与后端 app/services/consent_service.py 的 CURRENT_CONSENT_VERSIONS 保持一致：
 * 后端只接受"当前版本"的同意，版本不一致会 400 要求重新勾选。
 */
export const CONSENT_VERSIONS = {
  // v2：2026-09-05 生效，配套短信验证码功能（新增阿里云短信共享接收方、双通道找回、手机号抢占规则披露）
  privacy_policy: 'v2',
  oauth_sync: 'v1',
  phone_collection: 'v1',
  age_eligibility: 'v1',
} as const

export type ConsentType = keyof typeof CONSENT_VERSIONS

/** 传给后端的同意项：只包含用户**实际勾选**的项（未勾选的项不传，后端不记录）。 */
export interface ConsentAcceptance {
  privacy_policy?: string
  oauth_sync?: string
  phone_collection?: string
  age_eligibility?: string
}

/** 把勾选状态转换成后端入参：只带已勾选项，值为用户看到的条款版本。 */
export function buildConsentPayload(checked: Partial<Record<ConsentType, boolean>>): ConsentAcceptance {
  const payload: ConsentAcceptance = {}
  ;(Object.keys(CONSENT_VERSIONS) as ConsentType[]).forEach((type) => {
    if (checked[type]) {
      payload[type] = CONSENT_VERSIONS[type]
    }
  })
  return payload
}
