// P2-4.6：前端本地拦截与后端 app/core/password_policy.py 共用同一套规则
// （8 位 + 大小写 + 数字，修改时两端必须同步）。错误文案由调用方经 i18n
// 的双语 passwordPolicy.message 渲染，不再与后端共享字面文案。
export const PASSWORD_POLICY_ERROR_CODE = 'PASSWORD_POLICY'
export const PASSWORD_MIN_LENGTH = 8
export const PASSWORD_MAX_LENGTH = 50

export function checkPasswordStrength(password: string): string | null {
  if (
    !password ||
    password.length < PASSWORD_MIN_LENGTH ||
    password.length > PASSWORD_MAX_LENGTH ||
    !/[A-Z]/.test(password) ||
    !/[a-z]/.test(password) ||
    !/[0-9]/.test(password)
  ) {
    return PASSWORD_POLICY_ERROR_CODE
  }
  return null
}
