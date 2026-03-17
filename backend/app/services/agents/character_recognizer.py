"""
人物识别器 - 智能识别文本中的真实人物
"""
import re
from typing import List, Set, Tuple
from core.langchain_bridge import create_task_llm


class CharacterRecognizer:
    """人物识别器 - 区分真实人物和非人物词汇"""

    # 扩展的排除关键词列表
    EXCLUDE_KEYWORDS = {
        # 通用词汇
        '人物', '角色', '主角', '配角', '对手', '支持', '新增', '完整',
        '列表', '档案', '体系', '关系', '分布', '阵营', '所有', '更新',
        '姓名', '年龄', '性别', '外貌', '性格', '背景', '动机', '能力',
        '弱点', '成长', '关键', '重要', '次要', '群众', '主要', '辅助',

        # 描述性词汇
        '标志物', '衣料', '折痕', '花粉', '气味', '声音', '光线', '阴影',
        '甜而不腻', '苦涩', '清香', '浓郁', '淡雅', '华丽', '朴素',

        # 抽象概念
        '命运', '机遇', '挑战', '困境', '转折', '高潮', '结局', '开端',
        '冲突', '和解', '矛盾', '统一', '对立', '融合', '分裂',

        # 情节元素
        '线索', '伏笔', '悬念', '反转', '铺垫', '呼应', '暗示', '揭示',

        # 场景元素
        '场景', '地点', '环境', '氛围', '背景', '设定', '世界观',

        # 时间词
        '过去', '现在', '未来', '当下', '此刻', '瞬间', '永恒',
    }

    # 人物名称特征模式
    NAME_PATTERNS = [
        # 标准格式：【姓名】：张三
        (r'【姓名】[：:]\s*([\u4e00-\u9fa5]{2,4})', 'bracket_name'),
        # 加粗格式：**张三**（后面跟人物属性）
        (r'\*\*([\u4e00-\u9fa5]{2,4})\*\*\s*[：:]\s*(?:男|女|\d+岁)', 'bold_with_attr'),
        # 顿号分隔（需要上下文验证）
        (r'([一-龥]{2,4})、', 'comma_separated'),
    ]

    def __init__(self):
        """初始化识别器"""
        self.llm = create_task_llm(temperature=0.1)

    def is_valid_name(self, name: str) -> bool:
        """验证是否为有效人名

        Args:
            name: 待验证的名称

        Returns:
            是否为有效人名
        """
        # 基本过滤
        if not name or len(name) < 2 or len(name) > 4:
            return False

        # 排除关键词
        if name in self.EXCLUDE_KEYWORDS:
            return False

        # 排除纯数字、纯符号
        if re.match(r'^[\d\W]+$', name):
            return False

        # 排除常见非人名模式
        non_name_patterns = [
            r'^(第|之|其|此|该|这|那).+',  # 指示词开头
            r'.+(物|品|件|类|型|式)$',  # 物品后缀
            r'.+(感|味|香|色|光)$',  # 感官后缀
        ]

        for pattern in non_name_patterns:
            if re.match(pattern, name):
                return False

        return True

    def extract_names_with_confidence(self, text: str) -> List[Tuple[str, float, str]]:
        """提取人名并返回置信度

        Args:
            text: 待分析文本

        Returns:
            List of (name, confidence, source_pattern)
        """
        results = []
        seen_names = set()

        for pattern, source in self.NAME_PATTERNS:
            matches = re.findall(pattern, text)

            for name in matches:
                if name in seen_names:
                    continue

                if not self.is_valid_name(name):
                    continue

                # 根据匹配模式设置置信度
                if source == 'bracket_name':
                    confidence = 0.95  # 【姓名】格式最可靠
                elif source == 'bold_with_attr':
                    confidence = 0.90  # 加粗+属性也很可靠
                elif source == 'comma_separated':
                    confidence = 0.60  # 顿号分隔需要进一步验证
                else:
                    confidence = 0.50

                results.append((name, confidence, source))
                seen_names.add(name)

        return results

    def verify_names_with_context(self, names: List[str], context: str) -> List[Tuple[str, bool]]:
        """使用上下文验证人名

        Args:
            names: 待验证的人名列表
            context: 上下文文本

        Returns:
            List of (name, is_character)
        """
        if not names:
            return []

        # 构建验证提示词
        names_str = '、'.join(names)
        prompt = f"""请判断以下词汇是否为人物角色的名字。

【待验证词汇】
{names_str}

【上下文】
{context[:500]}

请对每个词汇判断：
- 如果是人物角色的名字，返回：是
- 如果是物品、场景、抽象概念等非人名，返回：否

只返回判断结果，格式：
词汇1: 是/否
词汇2: 是/否
..."""

        try:
            response = self.llm.invoke(prompt)
            result_text = response.content if hasattr(response, 'content') else str(response)

            # 解析结果
            results = []
            for line in result_text.strip().split('\n'):
                if ':' in line or '：' in line:
                    parts = re.split(r'[：:]', line)
                    if len(parts) == 2:
                        name = parts[0].strip()
                        is_char = '是' in parts[1]
                        if name in names:
                            results.append((name, is_char))

            return results

        except Exception as e:
            print(f"⚠️ AI验证失败: {e}")
            # 失败时保守处理，只保留高置信度的
            return [(name, True) for name in names]

    def count_characters(self, text: str, use_ai_verification: bool = True) -> Tuple[int, List[str]]:
        """智能统计人物数量

        Args:
            text: 人物设定文本
            use_ai_verification: 是否使用AI验证（低置信度的名字）

        Returns:
            (人物数量, 人物名称列表)
        """
        if not text or not text.strip():
            return 0, []

        # 第一步：提取候选人名
        candidates = self.extract_names_with_confidence(text)

        if not candidates:
            print("⚠️ 未识别到任何候选人名")
            return 0, []

        # 第二步：按置信度分类
        high_confidence = [(name, src) for name, conf, src in candidates if conf >= 0.85]
        low_confidence = [(name, src) for name, conf, src in candidates if conf < 0.85]

        confirmed_names = [name for name, _ in high_confidence]

        # 第三步：对低置信度的使用AI验证
        if low_confidence and use_ai_verification:
            low_conf_names = [name for name, _ in low_confidence]
            print(f"🔍 对 {len(low_conf_names)} 个低置信度词汇进行AI验证...")

            verified = self.verify_names_with_context(low_conf_names, text)
            for name, is_char in verified:
                if is_char:
                    confirmed_names.append(name)

        print(f"✅ 识别到 {len(confirmed_names)} 个人物: {', '.join(confirmed_names[:10])}{'...' if len(confirmed_names) > 10 else ''}")

        return len(confirmed_names), confirmed_names
