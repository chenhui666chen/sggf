export interface WorkflowGenerationModelDisplayLike {
  id: string
  name?: string | null
  cost_label?: string | null
  relative_cost_basis_label?: string | null
}

interface WorkflowGenerationModelProfile {
  feature: string
  speed: string
}

const FAST_SPEED = '响应较快，适合连续章节推进。'
const SLOW_SPEED = '偏慢，首包通常超过 30 秒。'
const VERY_SLOW_SPEED = '很慢，首包可能超过 1 分钟。'

const WORKFLOW_GENERATION_MODEL_PROFILES: Record<string, WorkflowGenerationModelProfile> = {
  'mimo-v2.5': {
    feature: '低成本均衡模型，适合常规章节快速推进。',
    speed: FAST_SPEED,
  },
  'mimo-v2.5-pro': {
    feature: 'MiMo 高配模型，适合质量优先的章节创作。',
    speed: FAST_SPEED,
  },
  'deepseek-v4-flash': {
    feature: '低成本大上下文模型，适合快速生成和批量推进。',
    speed: FAST_SPEED,
  },
  'deepseek-v4-pro': {
    feature: '质量更稳的大上下文模型，适合重要章节和复杂承接。',
    speed: FAST_SPEED,
  },
  'doubao-seed-character': {
    feature: '偏人物塑造和对白表现，适合角色互动密集章节。',
    speed: SLOW_SPEED,
  },
  'doubao-seed-evolving': {
    feature: '偏复杂剧情演进和长线推演，适合关键剧情节点。',
    speed: VERY_SLOW_SPEED,
  },
  'glm-5.2': {
    feature: '综合推理和结构控制较强，适合质量优先的重要章节。',
    speed: VERY_SLOW_SPEED,
  },
  'kimi/kimi-k2.6': {
    feature: '长文本叙事和中文表达较强，适合需要细腻文风的章节。',
    speed: SLOW_SPEED,
  },
  'minimax/minimax-m3': {
    feature: '文风和综合创作能力较强，适合质量优先的重点章节。',
    speed: VERY_SLOW_SPEED,
  },
  'qwen3.7-plus': {
    feature: '通用稳妥的均衡模型，适合日常章节生成。',
    speed: FAST_SPEED,
  },
  'step-3.7-flash': {
    feature: '结构化执行和稳定输出较好，适合追求稳妥结果的章节。',
    speed: SLOW_SPEED,
  },
}

function getBaseLabel(model: WorkflowGenerationModelDisplayLike): string {
  return model.name?.trim() || model.id
}

function getWorkflowGenerationModelProfile(modelId: string): WorkflowGenerationModelProfile {
  return WORKFLOW_GENERATION_MODEL_PROFILES[modelId.trim().toLowerCase()] || {
    feature: '可用于工作流章节创作，具体表现需以实际生成结果为准。',
    speed: '暂无实测速度。',
  }
}

export function formatWorkflowGenerationModelOptionLabel(
  model: WorkflowGenerationModelDisplayLike,
): string {
  const baseLabel = getBaseLabel(model)
  const costLabel = model.cost_label?.trim()

  if (!costLabel) {
    return `${baseLabel} · 成本未知`
  }

  return `${baseLabel} · 约 ${costLabel}`
}

export function formatWorkflowGenerationModelTooltip(
  model: WorkflowGenerationModelDisplayLike,
): string {
  const baseLabel = getBaseLabel(model)
  const profile = getWorkflowGenerationModelProfile(model.id)
  const costLabel = model.cost_label?.trim()
  const costBasisLabel = model.relative_cost_basis_label?.trim()
  const price = costLabel
    ? `约 ${costLabel}${costBasisLabel ? `（${costBasisLabel}）` : ''}。`
    : '成本未知。'

  return `${baseLabel}\n特点：${profile.feature}\n速度：${profile.speed}\n价格：${price}`
}
