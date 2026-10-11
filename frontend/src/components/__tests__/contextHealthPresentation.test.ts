// 上下文健康面板展示逻辑测试：冲突着色、缓存三态、在线调用标签、字节格式化。
import { describe, expect, it } from 'vitest'
import {
  formatObservedBytes,
  getCacheChip,
  getConflictChipColor,
  getOnlineCallLabel,
  getOutputStatusChip,
  getRequestStatusChip,
} from '@/components/contextHealthPresentation'

describe('getConflictChipColor', () => {
  const base = { blocking_conflict_count: 0, warning_conflict_count: 0 }

  it('passed 显示成功色', () => {
    expect(getConflictChipColor({ ...base, conflict_status: 'passed' })).toBe('success')
  })

  it('blocked 或存在 blocking 计数显示错误色', () => {
    expect(getConflictChipColor({ ...base, conflict_status: 'blocked' })).toBe('error')
    expect(
      getConflictChipColor({ ...base, conflict_status: 'unknown', blocking_conflict_count: 2 }),
    ).toBe('error')
  })

  it('warning 或存在 warning 计数显示警告色', () => {
    expect(getConflictChipColor({ ...base, conflict_status: 'warning' })).toBe('warning')
    expect(
      getConflictChipColor({ ...base, conflict_status: 'deferred', warning_conflict_count: 1 }),
    ).toBe('warning')
  })

  it('not_checked / unknown / 空值 / repaired 用中性色，不误报成功', () => {
    for (const status of ['not_checked', 'unknown', '', 'repaired']) {
      expect(getConflictChipColor({ ...base, conflict_status: status })).toBe('default')
    }
  })
})

describe('getCacheChip', () => {
  it('queried 显示命中数与默认色', () => {
    const chip = getCacheChip({
      cache_lookup_status: 'queried',
      cache_lookup_performed: true,
      rag_summary_cache_hits: 3,
    })
    expect(chip.label).toBe('缓存命中：3')
    expect(chip.color).toBe('default')
  })

  it('queried 但命中 0 仍区别于未查询', () => {
    const chip = getCacheChip({
      cache_lookup_status: 'queried',
      cache_lookup_performed: true,
      rag_summary_cache_hits: 0,
    })
    expect(chip.label).toBe('缓存命中：0')
    expect(chip.color).toBe('default')
  })

  it('unavailable / not_eligible 显示中性提示与警告色', () => {
    expect(
      getCacheChip({
        cache_lookup_status: 'unavailable',
        cache_lookup_performed: false,
        rag_summary_cache_hits: 0,
      }),
    ).toEqual({ label: '缓存：不可用', color: 'warning' })
    expect(
      getCacheChip({
        cache_lookup_status: 'not_eligible',
        cache_lookup_performed: false,
        rag_summary_cache_hits: 0,
      }),
    ).toEqual({ label: '缓存：无需查询', color: 'warning' })
  })

  it('旧数据无三态字段时按 cache_lookup_performed 回退', () => {
    expect(
      getCacheChip({
        cache_lookup_status: '',
        cache_lookup_performed: true,
        rag_summary_cache_hits: 2,
      }),
    ).toEqual({ label: '缓存命中：2', color: 'default' })
    expect(
      getCacheChip({
        cache_lookup_status: '',
        cache_lookup_performed: false,
        rag_summary_cache_hits: 0,
      }),
    ).toEqual({ label: '缓存：未查询', color: 'warning' })
  })
})

describe('getOnlineCallLabel', () => {
  it('扩写显示计划轮数而非在线 LLM', () => {
    expect(
      getOnlineCallLabel({ request_kind: 'expansion', online_llm_calls: 0, logical_step_count: 5 }),
    ).toBe('计划轮数：5')
  })

  it('正文/规划显示真实在线 LLM 调用次数', () => {
    expect(
      getOnlineCallLabel({ request_kind: 'content', online_llm_calls: 3, logical_step_count: 0 }),
    ).toBe('在线 LLM：3')
    expect(
      getOnlineCallLabel({ request_kind: 'plan', online_llm_calls: 2, logical_step_count: 0 }),
    ).toBe('在线 LLM：2')
  })

  it('拆分后的后续请求类型按真实在线 LLM 计数展示', () => {
    for (const kind of ['plan_retry', 'content_retry', 'regeneration', 'iteration_plan', 'revision', 'review'] as const) {
      expect(
        getOnlineCallLabel({ request_kind: kind, online_llm_calls: 1, logical_step_count: 0 }),
      ).toBe('在线 LLM：1')
    }
  })

  it('多模型评审成功：真实调用不可知(-1)时显示逻辑模型调用数', () => {
    expect(
      getOnlineCallLabel({ request_kind: 'review', online_llm_calls: -1, logical_step_count: 4 }),
    ).toBe('逻辑模型调用：4（真实不可知）')
  })

  it('回退/降级：真实调用不可知(-1)且无逻辑步骤时显示不可知', () => {
    expect(
      getOnlineCallLabel({ request_kind: 'fallback', online_llm_calls: -1, logical_step_count: 0 }),
    ).toBe('真实调用不可知')
  })
})

describe('getRequestStatusChip', () => {
  it('failed 显示错误色与异常类型', () => {
    expect(
      getRequestStatusChip({ request_status: 'failed', error_type: 'RuntimeError' }),
    ).toEqual({ label: '失败：RuntimeError', color: 'error' })
  })

  it('failed 无异常类型时仅显示失败', () => {
    expect(getRequestStatusChip({ request_status: 'failed', error_type: '' })).toEqual({
      label: '失败',
      color: 'error',
    })
  })

  it('ok / 空值不展示（返回 null）', () => {
    expect(getRequestStatusChip({ request_status: 'ok', error_type: '' })).toBeNull()
    expect(getRequestStatusChip({ request_status: '', error_type: '' })).toBeNull()
  })
})

describe('formatObservedBytes', () => {
  it('非负字节显示实际值与单位', () => {
    expect(formatObservedBytes(0)).toBe('0 B')
    expect(formatObservedBytes(2048)).toBe('2048 B')
  })

  it('-1 哨兵显示“未知”而非“-1 B”（多模型/同步 fallback/prompt 构造失败）', () => {
    expect(formatObservedBytes(-1)).toBe('未知')
  })
})

describe('getOutputStatusChip', () => {
  const base = { output_reject_reason: '', retry_status: 'not_needed', fallback_to_previous_output: false }

  it('rejected 显示错误色与中文拒绝原因（调用成功但输出不被采用）', () => {
    expect(
      getOutputStatusChip({ ...base, output_status: 'rejected', output_reject_reason: 'PlaceholderOutput' }),
    ).toEqual({ label: '输出被拒：占位模板', color: 'error' })
    expect(
      getOutputStatusChip({ ...base, output_status: 'rejected', output_reject_reason: 'RepeatedOutput' }),
    ).toEqual({ label: '输出被拒：与上一章重复', color: 'error' })
  })

  it('rejected 无已知原因码时回退原始字符串/纯文案', () => {
    expect(
      getOutputStatusChip({ ...base, output_status: 'rejected', output_reject_reason: 'WeirdCode' }),
    ).toEqual({ label: '输出被拒：WeirdCode', color: 'error' })
    expect(getOutputStatusChip({ ...base, output_status: 'rejected' })).toEqual({
      label: '输出被拒',
      color: 'error',
    })
  })

  it('截断/重生成重试失败显示警告色，区分是否回退上一版', () => {
    expect(
      getOutputStatusChip({
        ...base,
        output_status: 'accepted',
        retry_status: 'failed',
        fallback_to_previous_output: true,
      }),
    ).toEqual({ label: '重试失败：保留上一版', color: 'warning' })
    expect(
      getOutputStatusChip({ ...base, output_status: 'accepted', retry_status: 'failed' }),
    ).toEqual({ label: '重试失败', color: 'warning' })
  })

  it('rejected + 重试失败 + 回退：组合态合并展示，不丢失重试/回退信息（P2-3）', () => {
    expect(
      getOutputStatusChip({
        ...base,
        output_status: 'rejected',
        output_reject_reason: 'TruncatedOutput',
        retry_status: 'failed',
        fallback_to_previous_output: true,
      }),
    ).toEqual({ label: '输出被拒：截断；重试失败：保留上一版', color: 'error' })
  })

  it('rejected + 重试失败但未回退：组合态仍合并，保留错误色', () => {
    expect(
      getOutputStatusChip({
        ...base,
        output_status: 'rejected',
        output_reject_reason: 'EmptyOrShortOutput',
        retry_status: 'failed',
        fallback_to_previous_output: false,
      }),
    ).toEqual({ label: '输出被拒：空/过短；重试失败', color: 'error' })
  })

  it('accepted / not_checked / 重试成功 不展示（返回 null）避免噪声', () => {
    expect(getOutputStatusChip({ ...base, output_status: 'accepted' })).toBeNull()
    expect(getOutputStatusChip({ ...base, output_status: 'not_checked' })).toBeNull()
    expect(
      getOutputStatusChip({ ...base, output_status: 'accepted', retry_status: 'succeeded' }),
    ).toBeNull()
  })
})
