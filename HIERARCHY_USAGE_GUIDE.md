# 🎯 层级配置使用指南

## 📋 概述

本指南展示如何使用新优化的层级配置系统，包括23个体系类型的完整层级结构定义。

---

## 🏗️ 架构说明

### 1. 配置存储位置

**文件**: `backend/app/services/setting_templates.py`

**核心数据结构**: `HIERARCHY_DEFAULTS`

```python
HIERARCHY_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "cultivation_system": {
        "max_depth": 2,
        "levels": [
            {"depth": 1, "name": "境界体系", "type": "system"},
            {"depth": 2, "name": "境界详情", "type": "detail", "leaf": True},
        ],
    },
    "technique_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "功法体系", "type": "system"},
            {"depth": 2, "name": "功法分类", "type": "category", 
             "examples": ["心法", "剑法", "拳法", "身法", "刀法", "掌法"]},
            {"depth": 3, "name": "功法详情", "type": "detail", "leaf": True},
        ],
    },
    # ... 共23个体系
}
```

### 2. 自动注入机制

当用户应用模板时，系统会自动调用 `get_hierarchy_config_json(category)` 注入层级配置：

```python
# backend/app/api/v1/settings.py (第669行)
collection = SettingCollection(
    project_id=project_id,
    name=collection_data.get("name", ""),
    category=collection_data.get("category"),
    description=collection_data.get("description"),
    order=start_order + idx,
    max_depth=collection_data.get("max_depth") or (...),
    hierarchy_config=collection_data.get("hierarchy_config") or 
                     get_hierarchy_config_json(collection_data.get("category") or ""),  # 🔥 自动注入
)
```

---

## 📊 体系分类与层级设计

### 🎨 设计原则

1. **扁平体系（2层）**：用于有序关系的体系，通过关系边连接
   - 境界体系、人脉关系体系、候选集合

2. **分类体系（3层）**：最常见，适合大多数设定
   - 功法、丹药、阵法、符箓、武器等

3. **复杂体系（4层）**：地理等层级复杂的体系
   - 地图体系

### 📦 完整体系列表（23个）

#### 地理与世界观（1个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `map_system` | 地图体系 | 4层 | 地图体系 → 城镇聚落 → 主要城市 → 天元城 |

#### 修仙/玄幻体系（8个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `cultivation_system` | 境界体系 | 2层 | 境界体系 → 炼气期/筑基期/金丹期... |
| `technique_system` | 功法体系 | 3层 | 功法体系 → 剑法 → 太虚剑诀 |
| `pill_system` | 丹药体系 | 3层 | 丹药体系 → 突破丹药 → 筑基丹 |
| `formation_system` | 阵法体系 | 3层 | 阵法体系 → 防御阵 → 护山大阵 |
| `talisman_system` | 符箓体系 | 3层 | 符箓体系 → 攻击符 → 火球符 |
| `weapon_system` | 武器法宝体系 | 3层 | 武器法宝体系 → 武器 → 飞剑 |
| `resource_system` | 资源体系 | 3层 | 资源体系 → 灵草灵药 → 灵芝草 |
| `force_system` | 势力体系 | 3层 | 势力体系 → 宗门 → 天剑宗 |

#### 都市异能体系（5个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `ability_awakening_growth_system` | 异能觉醒体系 | 3层 | 异能体系 → 等级划分 → 觉醒者 |
| `hidden_organization_force_system` | 组织势力体系 | 3层 | 组织势力体系 → 官方机构 → 特殊事务管理局 |
| `network_social_relationship_system` | 人脉关系体系 | 2层 | 人脉关系体系 → 家族血脉 |
| `special_artifact_relic_system` | 道具遗物体系 | 3层 | 道具遗物体系 → 封印器具 → 能力抑制手铐 |
| `wealth_business_empire_system` | 财富商业体系 | 3层 | 财富商业体系 → 交易所 → 异能者交易中心 |

#### 西幻/魔法体系（3个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `magic_system` | 魔法体系 | 3层 | 魔法体系 → 元素魔法 → 火球术 |
| `race_bloodline_system` | 种族血脉体系 | 3层 | 种族血脉体系 → 常见种族 → 人类 |
| `profession_class_system` | 职业体系 | 3层 | 职业体系 → 战士系 → 狂战士 |

#### 科幻体系（2个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `interstellar_travel_exploration_system` | 星际航行体系 | 3层 | 星际航行体系 → 推进系统 → 跃迁引擎 |
| `ai_robot_system` | AI机器人体系 | 3层 | AI机器人体系 → 人工智能 → 超级智能 |

#### 末世废土体系（2个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `survivor_settlement_order_system` | 聚落秩序体系 | 3层 | 聚落秩序体系 → 营地据点 → 临时营地 |
| `mutation_infection_aberration_system` | 变异感染体系 | 3层 | 变异感染体系 → 辐射变异 → 辐射病变者 |

#### 游戏系统（1个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `game_skill_talent_system` | 技能天赋体系 | 3层 | 技能天赋体系 → 主动技能 → 烈焰斩 |

#### 角色体系（1个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `character_system` | 角色体系 | 3层 | 角色体系 → 主角团 → 李逍遥 |

#### 特殊体系（1个）
| 体系类别 | 中文名称 | 层级深度 | 结构示例 |
|---------|---------|---------|---------|
| `candidate` | 候选集合 | 2层 | 候选集合 → 待确认项 |

---

## 🎬 使用示例

### 示例1: 功法体系的完整树形结构

```
📦 功法体系 (technique_system)
│
├── 📁 剑法 (category)
│   ├── 📄 基础剑法 (detail)
│   ├── 📄 太虚剑诀 (detail)
│   └── 📄 万剑诀 (detail)
│
├── 📁 心法 (category)
│   ├── 📄 基础心法 (detail)
│   └── 📄 宗门镇派功法 (detail)
│
└── 📁 身法 (category)
    ├── 📄 凌波微步 (detail)
    └── 📄 神行百变 (detail)
```

### 示例2: 境界体系的扁平结构

```
📦 境界体系 (cultivation_system)
│
├── 📄 炼气期 (detail) ──前置→ 筑基期
├── 📄 筑基期 (detail) ──前置→ 金丹期
├── 📄 金丹期 (detail) ──前置→ 元婴期
├── 📄 元婴期 (detail) ──前置→ 化神期
└── 📄 化神期 (detail) ──前置→ 渡劫期
```

**注意**: 境界之间的前置关系通过 `KnowledgeGraphEdge` 表的关系边来表达，而不是通过层级结构。

### 示例3: 地图体系的4层复杂结构

```
📦 地图体系 (map_system)
│
├── 📁 城镇聚落 (category)
│   ├── 📂 主要城市 (list)
│   │   ├── 📄 天元城 (detail)
│   │   └── 📄 剑域城 (detail)
│   │
│   └── 📂 小型村镇 (list)
│       ├── 📄 青石村 (detail)
│       └── 📄 柳林镇 (detail)
│
└── 📁 秘境禁地 (category)
    └── 📂 远古遗迹 (list)
        └── 📄 剑冢 (detail)
```

---

## 🔧 前端使用方式

### 1. 获取集合的层级配置

```typescript
// frontend/src/pages/WorkflowControlPage.tsx

const collection = await apiClient.getSettingCollections(projectId);

// 解析层级配置
const hierarchyConfig = JSON.parse(collection.hierarchy_config);

console.log('最大深度:', hierarchyConfig.max_depth);
console.log('层级定义:', hierarchyConfig.levels);
```

### 2. 根据配置渲染树形视图

```tsx
// 前端已实现的递归树形渲染（WorkflowControlPage.tsx 第6300+行）

const renderTreeNodes = (nodes: TreeNode[], pathPrefix: string = '') => {
  return nodes.map((node) => {
    const nodeId = `${pathPrefix}/${encodeURIComponent(node.name)}`;
    
    return (
      <TreeItem
        key={nodeId}
        nodeId={nodeId}
        label={
          <Box sx={{ display: 'flex', alignItems: 'center', py: 0.5 }}>
            {node.is_leaf ? <DescriptionIcon /> : <FolderIcon />}
            <Typography sx={{ ml: 1 }}>{node.name}</Typography>
          </Box>
        }
      >
        {node.children && node.children.length > 0
          ? renderTreeNodes(node.children, nodeId)  // 🔥 递归渲染
          : null}
      </TreeItem>
    );
  });
};
```

### 3. 访问方式

1. 登录系统
2. 进入项目
3. 点击"世界观设定"按钮
4. 选择任一集合（如"功法体系"）
5. 系统自动根据 `hierarchy_config` 渲染树形结构

---

## 🎯 关键特性

### ✅ 自动化
- 应用模板时自动注入层级配置
- 无需手动设置，开箱即用

### ✅ 灵活性
- 支持2-4层不同深度
- 每个体系可以有独立的层级结构
- 支持动态扩展新体系

### ✅ 一致性
- 所有体系遵循统一的配置格式
- 前端通用的树形渲染逻辑

### ✅ 可维护性
- 集中管理在 `HIERARCHY_DEFAULTS`
- 修改一处，全局生效

---

## 📝 添加新体系

如需添加新的体系类型：

```python
# 在 HIERARCHY_DEFAULTS 中添加配置
HIERARCHY_DEFAULTS["your_new_system"] = {
    "max_depth": 3,
    "levels": [
        {"depth": 1, "name": "XX体系", "type": "system"},
        {"depth": 2, "name": "XX分类", "type": "category", 
         "examples": ["分类A", "分类B"]},
        {"depth": 3, "name": "XX详情", "type": "detail", "leaf": True},
    ],
}
```

---

## 🎊 总结

**当前状态**: ✅ 已完成23个体系的层级配置优化

**核心优势**:
- 🚀 自动注入，无需手动配置
- 🎨 灵活支持2-4层不同深度
- 🔄 前端自动适配，动态渲染
- 📦 统一管理，易于扩展

**下一步建议**:
1. 在前端UI中测试不同体系的树形展示效果
2. 根据实际使用体验调整层级划分
3. 为特殊体系添加自定义配置选项
