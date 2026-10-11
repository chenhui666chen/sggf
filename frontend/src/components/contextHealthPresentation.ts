// 上下文健康面板的纯展示逻辑：状态→颜色/标签映射，抽离为可测试的纯函数。
import type { ContextObservation } from '@/types/contextHealth'

export type ChipColor = 'default' | 'success' | 'warning' | 'error'

/**
 * 观测字节字段格式化：-1 为“未知”哨兵（多模型评审/同步 fallback/prompt 构造失败等
 * 服务内部构造、本层未捕获完整请求的场景），显示“未知”而非“-1 B”，
 * 避免把哨兵误读为负数大小；非负值显示实际字节数。适用于 prompt_request_bytes
 * 与 context_payload_bytes 等字节口径字段。
 */
export function formatObservedBytes(value: number): string {
  return value < 0 ? '未知' : `${value} B`
}

/**
 * 冲突状态着色：先判 conflict_status，再看计数。
 * not_checked / unknown / 空值 / repaired 等"非通过"态一律中性色，
 * 避免"尚未检查"或"已自动修复"被误显示为成功绿。
 */
export function getConflictChipColor(
  obs: Pick<
    ContextObservation,
    'conflict_status' | 'blocking_conflict_count' | 'warning_conflict_count'
  >,
): ChipColor {
  if (obs.conflict_status === 'passed') return 'success'
  if (obs.conflict_status === 'blocked' || obs.blocking_conflict_count > 0) return 'error'
  if (obs.conflict_status === 'warning' || obs.warning_conflict_count > 0) return 'warning'
  return 'default'
}

/**
 * 缓存查询三态标签与颜色：
 * queried→命中数（默认色）；unavailable/not_eligible→中性提示（警告色）；
 * 兼容无 cache_lookup_status 的旧数据，回退到 cache_lookup_performed 布尔。
 */
export function getCacheChip(
  obs: Pick<
    ContextObservation,
    'cache_lookup_status' | 'cache_lookup_performed' | 'rag_summary_cache_hits'
  >,
): { label: string; color: ChipColor } {
  const status = obs.cache_lookup_status
  if (status === 'queried') {
    return { label: `缓存命中：${obs.rag_summary_cache_hits}`, color: 'default' }
  }
  if (status === 'unavailable') return { label: '缓存：不可用', color: 'warning' }
  if (status === 'not_eligible') return { label: '缓存：无需查询', color: 'warning' }
  // 旧数据无三态字段时按布尔回退
  if (obs.cache_lookup_performed) {
    return { label: `缓存命中：${obs.rag_summary_cache_hits}`, color: 'default' }
  }
  return { label: '缓存：未查询', color: 'warning' }
}

/**
 * 在线调用标签：
 * - 扩写走多调用链路，无法可靠统计真实 LLM 调用，显示"计划轮数"；
 * - online_llm_calls=-1 为"真实调用不可知"哨兵（回退/降级/多模型聚合服务内部重试）：
 *   若带逻辑步骤数（如多模型"报告数+主导"）则显示逻辑模型调用数并标注真实不可知，
 *   否则直接显示"真实调用不可知"，避免把 -1 误呈现为"在线 LLM：-1"；
 * - 其余链路显示真实在线 LLM 调用次数（含内部重试/分段）。
 */
export function getOnlineCallLabel(
  obs: Pick<ContextObservation, 'request_kind' | 'online_llm_calls' | 'logical_step_count'>,
): string {
  if (obs.request_kind === 'expansion') return `计划轮数：${obs.logical_step_count}`
  if (obs.online_llm_calls === -1) {
    return obs.logical_step_count > 0
      ? `逻辑模型调用：${obs.logical_step_count}（真实不可知）`
      : '真实调用不可知'
  }
  return `在线 LLM：${obs.online_llm_calls}`
}

/**
 * 请求状态标签：失败请求（含锁定模型直接终止）需醒目展示异常类型；
 * ok/旧数据无该字段时返回 null（不展示），避免噪声。
 */
export function getRequestStatusChip(
  obs: Pick<ContextObservation, 'request_status' | 'error_type'>,
): { label: string; color: ChipColor } | null {
  if (obs.request_status === 'failed') {
    return { label: obs.error_type ? `失败：${obs.error_type}` : '失败', color: 'error' }
  }
  return null
}

/**
 * 输出被拒原因的稳定错误码 → 中文标签映射（与后端 F.6 evaluate_chapter_output 的 5 个稳定拒绝码对齐）。
 * 未知码回退为原始字符串，避免信息丢失。
 */
const OUTPUT_REJECT_REASON_LABELS: Record<string, string> = {
  EmptyOutput: '空输出',
  PlaceholderOutput: '占位模板',
  RepeatedOutput: '与上一章重复',
  EmptyOrShortOutput: '空/过短',
  TruncatedOutput: '截断',
  InvalidOutput: '无效',
}

/**
 * 输出验收标签（②③）：request_status 表示“调用是否成功”，output_status 表示“产出是否被采用”，
 * 二者解耦。LLM 调用成功但输出被拒（空/占位/重复/过短/截断）时，仅看 request_status 会误显示为成功，
 * 故独立展示：
 * - output_status=rejected → 错误色，附拒绝原因；
 * - retry_status=failed → 警告色，标注是否回退到上一版；
 * - 两者可同时成立（如截断重试仍失败→保留上一版且判 rejected），合并为一个标签同时展示，
 *   不因先判 rejected 提前返回而丢失“重试失败/回退上一版”动作（P2-3）；
 * - 其余（accepted / not_checked / retry succeeded）返回 null，不制造噪声。
 */
export function getOutputStatusChip(
  obs: Pick<
    ContextObservation,
    'output_status' | 'output_reject_reason' | 'retry_status' | 'fallback_to_previous_output'
  >,
): { label: string; color: ChipColor } | null {
  const rejected = obs.output_status === 'rejected'
  const retryFailed = obs.retry_status === 'failed'
  const parts: string[] = []
  if (rejected) {
    const reason = OUTPUT_REJECT_REASON_LABELS[obs.output_reject_reason] || obs.output_reject_reason
    parts.push(reason ? `输出被拒：${reason}` : '输出被拒')
  }
  if (retryFailed) {
    parts.push(obs.fallback_to_previous_output ? '重试失败：保留上一版' : '重试失败')
  }
  if (parts.length === 0) {
    return null
  }
  // rejected 为更严重状态：输出被拒即用错误色，仅重试失败（输出仍被采用）用警告色。
  return { label: parts.join('；'), color: rejected ? 'error' : 'warning' }
}
