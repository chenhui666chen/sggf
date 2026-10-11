import { describe, expect, it } from 'vitest'

import { CONSENT_VERSIONS, buildConsentPayload, type ConsentType } from '@/constants/consent'

describe('buildConsentPayload（P2-5.2）', () => {
  it('未勾选任何条款时不产出任何同意项（后端不会代为记录）', () => {
    expect(buildConsentPayload({})).toEqual({})
  })

  it('只带用户实际勾选的项，未勾选的项不出现在入参里', () => {
    const payload = buildConsentPayload({ privacy_policy: true })

    expect(payload).toEqual({ privacy_policy: CONSENT_VERSIONS.privacy_policy })
    expect(payload.oauth_sync).toBeUndefined()
    expect(payload.phone_collection).toBeUndefined()
  })

  it('勾选手机号收集时才携带 phone_collection（敏感个人信息需单独同意）', () => {
    const payload = buildConsentPayload({ privacy_policy: true, phone_collection: true })

    expect(Object.keys(payload).sort()).toEqual(['phone_collection', 'privacy_policy'])
  })

  it('值为当前生效版本，与后端 CURRENT_CONSENT_VERSIONS 对齐', () => {
    const allChecked: Partial<Record<ConsentType, boolean>> = {
      privacy_policy: true,
      oauth_sync: true,
      phone_collection: true,
      age_eligibility: true,
    }

    expect(buildConsentPayload(allChecked)).toEqual({ ...CONSENT_VERSIONS })
  })

  it('取消勾选后该项从入参中移除', () => {
    const before = buildConsentPayload({ privacy_policy: true, oauth_sync: true })
    const after = buildConsentPayload({ ...before, oauth_sync: false } as Partial<
      Record<ConsentType, boolean>
    >)

    expect(after.oauth_sync).toBeUndefined()
    expect(after.privacy_policy).toBe(CONSENT_VERSIONS.privacy_policy)
  })
})
