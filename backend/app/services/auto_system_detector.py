"""
自动体系检测服务
根据文本内容自动识别涉及的体系类型，并创建对应的设定集合
"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.agents.llm_singleton import create_deepseek_llm

logger = logging.getLogger("uvicorn.error")

# 27种体系类型映射
SYSTEM_CATEGORIES = {
    # 地理与世界观
    "map_system": "地图体系",
    
    # 修仙/玄幻体系
    "cultivation_realm_system": "修仙境界体系",
    "martial_realm_system": "武道境界体系",
    "technique_system": "功法体系",
    "pill_system": "丹药体系",
    "formation_system": "阵法体系",
    "talisman_system": "符箓体系",
    "weapon_system": "武器与法宝体系",
    "resource_system": "资源体系",
    "force_system": "势力体系",
    
    # 都市异能体系
    "ability_realm_system": "异能境界体系",
    "ability_awakening_growth_system": "异能体系",
    "hidden_organization_force_system": "组织势力体系",
    "network_social_relationship_system": "人脉关系体系",
    "special_artifact_relic_system": "道具遗物体系",
    "wealth_business_empire_system": "财富商业体系",
    
    # 西幻/魔法体系
    "magic_realm_system": "魔法境界体系",
    "magic_system": "魔法体系",
    "race_bloodline_system": "种族血脉体系",
    "profession_class_system": "职业体系",
    
    # 科幻体系
    "interstellar_travel_exploration_system": "星际航行体系",
    "ai_robot_system": "AI机器人体系",
    
    # 末世废土体系
    "survivor_settlement_order_system": "聚落秩序体系",
    "mutation_infection_aberration_system": "变异感染体系",
    
    # 游戏系统体系
    "skill_talent_system": "技能天赋体系",
    
    # 角色体系
    "character_system": "角色体系",
    
    # 特殊
    "organization_system": "组织体系",
}


class AutoSystemDetector:
    """自动体系检测器"""
    
    def __init__(self):
        """初始化检测器"""
        self.llm = create_deepseek_llm(task_type="entity_extract")
    
    def detect_systems(self, content: str) -> List[str]:
        """
        分析文本内容，检测涉及的体系类型
        
        Args:
            content: 待分析的文本内容（大纲或章节）
        
        Returns:
            检测到的体系类型列表（category key）
        """
        if not content or len(content.strip()) < 50:
            logger.info("⚠️ 文本内容过短，跳过体系检测")
            return []
        
        prompt = f"""# 任务：分析以下小说内容，识别其中涉及的体系类型

## 可选体系类型（27种）

### 地理与世界观
- map_system: 地图体系（涉及地理位置、地图、区域划分等）

### 修仙/玄幻体系
- cultivation_realm_system: 修仙境界体系（如筑基、金丹、元婴等）
- martial_realm_system: 武道境界体系（如后天、先天、宗师等）
- technique_system: 功法体系（如功法、武学、心法等）
- pill_system: 丹药体系（如丹药、灵丹、仙丹等）
- formation_system: 阵法体系（如阵法、禁制、结界等）
- talisman_system: 符箓体系（如符箓、符文、咒符等）
- weapon_system: 武器与法宝体系（如法宝、灵器、仙器等）
- resource_system: 资源体系（如灵石、材料、宝物等）
- force_system: 势力体系（如宗门、门派、家族等）

### 都市异能体系
- ability_realm_system: 异能境界体系（如觉醒、进化等级等）
- ability_awakening_growth_system: 异能体系（如火系、冰系、精神系等）
- hidden_organization_force_system: 组织势力体系（如异能组织、秘密机构等）
- network_social_relationship_system: 人脉关系体系（如社交网络、人际关系等）
- special_artifact_relic_system: 道具遗物体系（如古代遗物、神器等）
- wealth_business_empire_system: 财富商业体系（如商业帝国、集团等）

### 西幻/魔法体系
- magic_realm_system: 魔法境界体系（如魔法学徒、魔法师等）
- magic_system: 魔法体系（如元素魔法、黑暗魔法等）
- race_bloodline_system: 种族血脉体系（如精灵、矮人、血统等）
- profession_class_system: 职业体系（如战士、法师、盗贼等）

### 科幻体系
- interstellar_travel_exploration_system: 星际航行体系（如星际旅行、太空探索等）
- ai_robot_system: AI机器人体系（如人工智能、机器人等）

### 末世废土体系
- survivor_settlement_order_system: 聚落秩序体系（如幸存者基地、避难所等）
- mutation_infection_aberration_system: 变异感染体系（如丧尸病毒、变异等）

### 游戏系统体系
- skill_talent_system: 技能天赋体系（如技能树、天赋系统等）

### 角色与组织
- character_system: 角色体系（如主角、配角等人物设定）
- organization_system: 组织体系（如组织、团体、联盟等）

## 待分析内容
{content[:3000]}

## 输出要求
请分析以上内容，识别其中涉及的体系类型，并以JSON格式输出：

{{
  "detected_systems": ["cultivation_realm_system", "technique_system", "pill_system"],
  "reasoning": "文本中提到了筑基、金丹等修仙境界，涉及修仙境界体系；提到了功法修炼，涉及功法体系；提到了丹药炼制，涉及丹药体系。"
}}

**重要规则**：
1. 只输出JSON格式，不要其他内容
2. detected_systems数组中只包含确实在文本中出现的体系（不要臆测）
3. 如果文本内容不明确或未涉及任何体系，返回空数组
4. 最多识别10个体系，优先识别最核心的体系
"""
        
        try:
            logger.info("🔍 开始AI分析文本，识别体系类型...")
            response = self.llm.process(prompt, {})
            
            # 解析JSON响应
            import json
            # 提取JSON部分（去除可能的markdown代码块标记）
            response_text = response.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            result = json.loads(response_text.strip())
            detected_systems = result.get("detected_systems", [])
            reasoning = result.get("reasoning", "")
            
            # 验证返回的体系类型是否有效
            valid_systems = [s for s in detected_systems if s in SYSTEM_CATEGORIES]
            
            logger.info(f"✅ 检测到 {len(valid_systems)} 个体系: {valid_systems}")
            logger.info(f"   推理: {reasoning}")
            
            return valid_systems
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ AI返回的JSON格式无效: {e}")
            logger.error(f"   响应内容: {response[:500]}")
            return []
        except Exception as e:
            logger.error(f"❌ 体系检测失败: {e}")
            import traceback
            traceback.print_exc()
            return []


async def auto_create_system_collections(
    project_id: int,
    content: str,
    db: Session,
    content_type: str = "outline"  # "outline" 或 "chapter"
) -> Dict[str, Any]:
    """
    自动检测并创建体系集合（异步非阻塞）
    
    Args:
        project_id: 项目ID
        content: 待分析的内容
        db: 数据库会话
        content_type: 内容类型（用于日志）
    
    Returns:
        {
            "created_collections": ["修仙境界体系", "功法体系"],
            "existing_collections": ["丹药体系"],
            "total_detected": 3
        }
    """
    import asyncio
    from datetime import datetime
    
    logger.info(f"📚 开始自动检测{content_type}中的体系类型（项目ID: {project_id}）")
    
    try:
        # 使用线程池执行AI分析，避免阻塞
        detector = AutoSystemDetector()
        detected_categories = await asyncio.to_thread(
            detector.detect_systems,
            content
        )
        
        if not detected_categories:
            logger.info("   ℹ️ 未检测到任何体系类型")
            return {
                "created_collections": [],
                "existing_collections": [],
                "total_detected": 0
            }
        
        # 查询项目中已存在的集合
        query = text("""
            SELECT category 
            FROM setting_collections 
            WHERE project_id = :project_id
        """)
        result = db.execute(query, {"project_id": project_id})
        existing_categories = {row[0] for row in result.fetchall()}
        
        # 需要创建的集合
        to_create = [cat for cat in detected_categories if cat not in existing_categories]
        already_exists = [cat for cat in detected_categories if cat in existing_categories]
        
        created_names = []
        
        # 创建缺失的集合
        for category in to_create:
            category_name = SYSTEM_CATEGORIES.get(category, category)
            
            insert_query = text("""
                INSERT INTO setting_collections 
                (project_id, name, category, description, created_at, updated_at, "order")
                VALUES (:project_id, :name, :category, :description, :created_at, :updated_at, :order)
            """)
            
            db.execute(insert_query, {
                "project_id": project_id,
                "name": category_name,
                "category": category,
                "description": f"系统自动创建的{category_name}",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "order": 999  # 自动创建的放在最后
            })
            
            created_names.append(category_name)
            logger.info(f"   ✅ 已创建集合: {category_name}")
        
        db.commit()
        
        existing_names = [SYSTEM_CATEGORIES.get(cat, cat) for cat in already_exists]
        
        logger.info(f"📚 体系检测完成: 创建{len(created_names)}个，已存在{len(existing_names)}个")
        
        return {
            "created_collections": created_names,
            "existing_collections": existing_names,
            "total_detected": len(detected_categories)
        }
        
    except Exception as e:
        logger.error(f"❌ 自动创建体系集合失败: {e}")
        import traceback
        traceback.print_exc()
        # 静默失败，不影响主流程
        return {
            "created_collections": [],
            "existing_collections": [],
            "total_detected": 0,
            "error": str(e)
        }
