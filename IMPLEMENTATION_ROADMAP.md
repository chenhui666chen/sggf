# 实施路线图 - 具体执行方案

## 一、新增模块清单

### 模块1：AI痕迹降低处理器（优先级P1）
**文件**：`ai_trace_reduction_processor.py`
**功能**：对生成的文本进行二次精修，实现四层精修体系
**集成点**：`agent_coordinator.py` 的质量评审阶段之后

**核心方法**：
```python
class AITraceReductionProcessor:
    def reduce_ai_traces(self, content: str, context: Dict) -> str:
        """主方法：降低AI痕迹"""
        
    def inject_author_voice(self, content: str, voice_profile: Dict) -> str:
        """第一层：注入作者腔调"""
        
    def optimize_narrative_structure(self, content: str) -> str:
        """第二层：优化叙事结构"""
        
    def enhance_dialogue_authenticity(self, content: str) -> str:
        """第三层：增强对话真实性"""
        
    def refine_language_details(self, content: str) -> str:
        """第四层：精修语言细节"""
```

### 模块2：作者腔调系统（优先级P1）
**文件**：`author_voice_system.py`
**功能**：管理和应用作者腔调
**核心类**：
```python
class AuthorVoiceProfile:
    narrative_style: str      # 叙事风格
    value_system: Dict        # 价值观
    unique_traits: List       # 独特特征
    emotional_depth: str      # 情感深度
    
class AuthorVoiceManager:
    def create_voice_profile(self, project_id: int) -> AuthorVoiceProfile
    def apply_voice_to_prompt(self, prompt: str, profile: AuthorVoiceProfile) -> str
    def validate_voice_consistency(self, content: str, profile: AuthorVoiceProfile) -> float
```

### 模块3：对话真实性模块（优先级P1）
**文件**：`dialogue_authenticity_module.py`
**功能**：增强对话的真实性和潜台词
**核心方法**：
```python
class DialogueAuthenticityEngine:
    def add_subtext(self, dialogue: str) -> str:
        """添加潜台词"""
        
    def inject_interruptions(self, dialogue: str) -> str:
        """注入打断和重复"""
        
    def add_filler_words(self, dialogue: str) -> str:
        """添加废话和情绪词"""
        
    def optimize_dialogue_rhythm(self, dialogue: str) -> str:
        """优化对话节奏"""
```

### 模块4：人物复杂性引擎（优先级P2）
**文件**：`character_complexity_engine.py`
**功能**：赋予人物矛盾特质和细节
**核心方法**：
```python
class CharacterComplexityEngine:
    def add_contradictions(self, character_profile: Dict) -> Dict:
        """添加矛盾特质"""
        
    def generate_detail_actions(self, character_profile: Dict) -> List:
        """生成细节动作"""
        
    def create_unique_thinking_patterns(self, character_profile: Dict) -> Dict:
        """创建独特思维模式"""
```

### 模块5：语言精修引擎（优先级P2）
**文件**：`language_refinement_engine.py`
**功能**：优化词汇、句式、五感描写
**核心方法**：
```python
class LanguageRefinementEngine:
    def optimize_vocabulary(self, text: str) -> str:
        """优化词汇"""
        
    def enhance_sentence_rhythm(self, text: str) -> str:
        """增强句式节奏"""
        
    def inject_sensory_details(self, text: str) -> str:
        """注入五感细节"""
        
    def remove_clichés(self, text: str) -> str:
        """移除陈词滥调"""
```

### 模块6：叙事结构优化器（优先级P3）
**文件**：`narrative_structure_optimizer.py`
**功能**：打破三幕剧模板，支持非线性叙事
**核心方法**：
```python
class NarrativeStructureOptimizer:
    def support_non_linear_narrative(self, plot: str) -> str:
        """支持非线性叙事"""
        
    def introduce_randomness(self, plot: str) -> str:
        """引入随机性"""
        
    def optimize_pacing(self, plot: str) -> str:
        """优化节奏"""
```

---

## 二、需要修改的现有文件

### 修改1：agents.py - ContentCreatorAgent
**位置**：第206-214行
**改进**：更新系统提示词，注入作者腔调和灵魂指导

**当前**：
```python
def get_system_prompt(self) -> str:
    return """你是一位杰出的内容创作师，文笔优美、叙述生动。
    ...
    请创作高质量的文学作品，注重细节描写、对话、心理活动和场景营造。"""
```

**改进后**：
```python
def get_system_prompt(self) -> str:
    return """你是一位具有独特风格的小说作家。
    
【创作原则】
1. 注入"人"的灵魂：展现独特的价值观和道德立场
2. 打破完美：引入生活的随机性和不完美
3. 深化人物：赋予矛盾特质，展现内心挣扎
4. 真实对话：加入潜台词、打断、废话
5. 精细语言：具体词汇、五感细节、节奏变化

【禁止事项】
- 不要使用"杰出"、"优美"等套路词汇
- 不要让所有伏笔都完美回收
- 不要让人物完全符合设定
- 不要让对话信息密度过高
- 不要过度使用华丽辞藻

请创作具有"作者灵魂"的文学作品。"""
```

### 修改2：agent_coordinator.py - 章节创作提示词
**位置**：第678-701行
**改进**：添加四层精修要求

**新增内容**：
```python
# 在 content_prompt 中添加
【四层精修要求】

【第一层：灵魂注入】
- 体现作者的独特价值观和道德立场
- 设置道德困境，避免绝对的对错
- 让人物面临真实的选择和代价

【第二层：结构节奏】
- 避免过于完美的情节推进
- 引入意外事件和随机性
- 张弛有度的节奏安排

【第三层：人物对话】
- 人物展现矛盾特质，不完全符合设定
- 对话包含潜台词和言外之意
- 加入打断、重复、废话等真实元素

【第四层：语言细节】
- 使用具体词汇替代抽象表述
- 长短句交错，增强节奏感
- 系统加入五感细节（听觉、嗅觉、触觉、味觉）
```

### 修改3：agent_coordinator.py - 质量评审标准
**位置**：`_stage_four_quality_review()` 方法
**改进**：添加"AI痕迹"评估维度

**新增评审标准**：
```python
# 在 review_prompt 中添加
【AI痕迹评估】
1. 作者腔调一致性：是否体现了独特的作者风格？
2. 灵魂深度：是否有真实的人性思考？
3. 对话真实性：对话是否包含潜台词和真实元素？
4. 人物复杂性：人物是否有矛盾特质？
5. 语言自然性：是否避免了套路和堆砌？
6. 情节真实性：是否包含"生活的随机性"？
```

### 修改4：agent_coordinator.py - 迭代优化流程
**位置**：`_stage_five_iteration_optimization()` 方法
**改进**：添加AI痕迹降低处理

**新增步骤**：
```python
# 在迭代优化中添加
# 步骤1：基于评审反馈修改
revised_content = self.content_creator.process(revision_prompt, ...)

# 步骤2：应用AI痕迹降低处理（新增）
from ai_trace_reduction_processor import AITraceReductionProcessor
processor = AITraceReductionProcessor()
refined_content = processor.reduce_ai_traces(revised_content, self.project_context)

# 步骤3：重新评审
final_review = self.quality_reviewer.process(re_review_prompt, ...)
```

---

## 三、集成点规划

### 集成点1：项目初始化
**位置**：`agent_coordinator.py` 的 `__init__` 方法
**操作**：初始化作者腔调系统和AI痕迹处理器

### 集成点2：章节创作
**位置**：`_stage_three_content_creation()` 方法
**操作**：在内容生成后应用AI痕迹降低处理

### 集成点3：质量评审
**位置**：`_stage_four_quality_review()` 方法
**操作**：添加AI痕迹评估维度

### 集成点4：迭代优化
**位置**：`_stage_five_iteration_optimization()` 方法
**操作**：在修改后应用AI痕迹降低处理

---

## 四、实施时间表

| 阶段 | 任务 | 预计时间 | 优先级 |
|------|------|--------|--------|
| 第1周 | 创建核心模块（P1） | 3天 | P1 |
| 第1周 | 修改现有Prompt | 2天 | P1 |
| 第2周 | 创建增强模块（P2） | 3天 | P2 |
| 第2周 | 集成和测试 | 2天 | P2 |
| 第3周 | 创建可选模块（P3） | 2天 | P3 |
| 第3周 | 优化和调整 | 3天 | P3 |


