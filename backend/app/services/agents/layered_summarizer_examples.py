"""
分层摘要策略 - 使用示例

展示如何在不同场景中使用分层摘要器优化上下文
"""

from backend.app.services.agents.layered_summarizer import prepare_smart_context
from backend.app.services.agents.knowledge_base import NovelKnowledgeBase


# ============================================================================
# 场景1: 大纲扩展 (30章 → 80章)
# ============================================================================

def example_outline_expansion():
    """示例: 大纲扩展场景"""
    
    # 准备数据
    outline = """[这里是30章的大纲，约5万字]..."""
    characters = """[这里是人物设定，约3万字]..."""
    worldview = """[这里是世界观设定，约1万字]..."""
    
    # 使用分层摘要器
    result = prepare_smart_context(
        outline=outline,
        characters=characters,
        worldview=worldview,
        scenario="outline_expand",  # 大纲扩展场景
        current_count=30,  # 当前30章
        knowledge_base=NovelKnowledgeBase()
    )
    
    # 查看结果
    print(f"选择的模型: {result['selected_model']}")  # qwen3-max (30章)
    print(f"优化后上下文: {len(result['context'])}字符")
    print(f"Token使用: {result['stats']['total_tokens']:,} / {result['stats']['target_tokens']:,}")
    
    # 使用优化后的上下文调用LLM
    # llm.invoke([HumanMessage(content=result['context'])])


# ============================================================================
# 场景2: 大纲扩展 (80章 → 150章) - 自动切换qwen-long
# ============================================================================

def example_large_outline_expansion():
    """示例: 大规模大纲扩展"""
    
    outline = """[这里是80章的大纲，约15万字]..."""
    characters = """[这里是50个人物，约5万字]..."""
    worldview = """[这里是复杂世界观，约2万字]..."""
    
    result = prepare_smart_context(
        outline=outline,
        characters=characters,
        worldview=worldview,
        scenario="outline_expand",
        current_count=80,  # 当前80章
    )
    
    # 自动选择qwen-long，放宽限制
    print(f"选择的模型: {result['selected_model']}")  # qwen-long
    print(f"压缩比: {result['stats']['compression_ratio']*100:.1f}%")
    
    # 分层摘要结果:
    # - 骨架: 覆盖全书1-80章的结构和转折点
    # - 详细: 聚焦第70-90章的详细内容
    # - 总输入: 约300,000 tokens (qwen-long 30%使用率)


# ============================================================================
# 场景3: 章节生成 (第50章) - 聚焦当前章节
# ============================================================================

def example_chapter_generation():
    """示例: 章节生成场景"""
    
    outline = """[完整大纲80章]..."""
    characters = """[完整人物设定]..."""
    worldview = """[世界观设定]..."""
    
    result = prepare_smart_context(
        outline=outline,
        characters=characters,
        worldview=worldview,
        scenario="chapter_generation",
        current_count=50,  # 当前生成第50章
        focus_range=(40, 60)  # 聚焦第40-60章
    )
    
    # 分层摘要结果:
    # - 骨架: 全书1-80章的结构
    # - 详细: 仅第40-60章的详细内容 (RAG检索或正则提取)
    # - 模型: qwen-long (50章已超过20章阈值)
    
    print(f"详细片段tokens: {result['stats']['detail_tokens']:,}")


# ============================================================================
# 场景4: 人物扩展 (20人 → 50人)
# ============================================================================

def example_character_expansion():
    """示例: 人物扩展场景"""
    
    outline = """[大纲]..."""
    characters = """[当前20个人物]..."""
    worldview = """[世界观]..."""
    
    result = prepare_smart_context(
        outline=outline,
        characters=characters,
        worldview=worldview,
        scenario="character_expand",  # 人物扩展场景
        current_count=20,  # 当前20人
    )
    
    # 自动选择deepseek-r1 (20人以内)
    print(f"选择的模型: {result['selected_model']}")  # deepseek-r1
    
    # 如果是50人，会自动切换到qwen-plus


# ============================================================================
# 对比: 不同章节数的模型选择
# ============================================================================

def example_model_selection():
    """展示不同规模下的自动模型选择"""
    
    test_cases = [
        (10, "outline_expand"),   # qwen3-max
        (30, "outline_expand"),   # qwen3-max
        (50, "outline_expand"),   # qwen-plus
        (80, "outline_expand"),   # qwen-long
        (150, "outline_expand"),  # qwen-long
    ]
    
    for count, scenario in test_cases:
        result = prepare_smart_context(
            outline="[示例大纲]",
            characters="[示例人物]",
            worldview="[示例世界观]",
            scenario=scenario,
            current_count=count
        )
        
        print(f"{count}章 → {result['selected_model']} (目标tokens: {result['stats']['target_tokens']:,})")
    
    # 输出:
    # 10章 → qwen3-max (目标tokens: 26,112)
    # 30章 → qwen-plus (目标tokens: 600,000)
    # 50章 → qwen-plus (目标tokens: 600,000)
    # 80章 → qwen-long (目标tokens: 3,000,000)
    # 150章 → qwen-long (目标tokens: 3,000,000)


# ============================================================================
# 实际集成示例: 大纲扩展器中使用
# ============================================================================

def example_integration_in_outline_expander():
    """展示如何在OutlineExpander中集成"""
    
    from backend.app.services.agents.outline_expander import OutlineExpander
    
    # 初始化扩展器
    expander = OutlineExpander(
        knowledge_base=NovelKnowledgeBase(),
        genre="修仙",
        planned_chapters_max=100
    )
    
    # 在expand_plot_outline_incremental方法中使用
    current_outline = """[当前大纲]..."""
    characters = """[人物设定]..."""
    world_setting = """[世界观]..."""
    current_chapter_count = 50
    
    # 🎆 使用分层摘要器准备上下文
    context_result = expander.layered_summarizer.prepare_context_for_expansion(
        outline=current_outline,
        characters=characters,
        worldview=world_setting,
        scenario="outline_expand",
        current_count=current_chapter_count
    )
    
    # 使用优化后的上下文
    optimized_context = context_result["context"]
    selected_model = context_result["selected_model"]
    
    # 🔥 使用选择的模型进行扩展
    from langchain_openai import ChatOpenAI
    from backend.app.services.agents.config import Config
    
    llm = ChatOpenAI(
        model=selected_model,
        temperature=0.7,
        api_key=Config.DEEPSEEK_API_KEY if selected_model.startswith("deepseek") else os.getenv("DASHSCOPE_API_KEY"),
        base_url=Config.DEEPSEEK_API_BASE if selected_model.startswith("deepseek") else "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    # 调用LLM
    # result = llm.invoke([HumanMessage(content=optimized_context)])


if __name__ == "__main__":
    # 运行示例
    print("=" * 70)
    print("分层摘要策略 - 使用示例")
    print("=" * 70)
    
    # example_outline_expansion()
    # example_large_outline_expansion()
    # example_chapter_generation()
    # example_character_expansion()
    example_model_selection()
