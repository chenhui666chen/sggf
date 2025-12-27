"""
测试有声小说Agent的模型配置

验证每个Agent使用了正确的大模型
"""
import asyncio
from app.services.model_optimizer import get_model_optimizer, TaskType


def test_audiobook_model_allocation():
    """测试有声小说Agent的模型分配"""
    
    print("="*70)
    print("🎙️ 有声小说Agent模型分配测试")
    print("="*70 + "\n")
    
    # 测试保守策略
    print("【保守优化策略】（推荐）\n")
    optimizer = get_model_optimizer("conservative")
    
    audiobook_tasks = [
        (TaskType.AUDIOBOOK_DIRECTOR, "有声导演", "综合分析策略制定"),
        (TaskType.AUDIOBOOK_SCRIPT, "剧本编剧", "创意改编+逻辑推理"),
        (TaskType.AUDIOBOOK_VOICE, "音色设计", "规则匹配音色参数"),
        (TaskType.AUDIOBOOK_SOUND, "音效设计", "场景音效规划"),
        (TaskType.AUDIOBOOK_MUSIC, "音乐设计", "情绪音乐匹配"),
        (TaskType.AUDIOBOOK_REVIEW, "质量评审", "多维度质量分析"),
    ]
    
    for task_type, agent_name, task_desc in audiobook_tasks:
        model = optimizer.select_model(task_type)
        print(f"✓ {agent_name:12} → {model:18} ({task_desc})")
    
    # 测试激进策略
    print("\n【激进优化策略】（最大化速度）\n")
    optimizer_aggressive = get_model_optimizer("aggressive")
    
    for task_type, agent_name, task_desc in audiobook_tasks:
        model = optimizer_aggressive.select_model(task_type)
        print(f"✓ {agent_name:12} → {model:18} ({task_desc})")
    
    # 性能预测
    print("\n" + "="*70)
    print("📊 模型选择理由")
    print("="*70 + "\n")
    
    reasons = {
        "AudioDirector": {
            "模型": "qwen3-max",
            "理由": "需要综合分析小说类型、目标听众，制定改编策略，qwen3-max在多维度分析上表现均衡"
        },
        "AudiobookScriptAdapter": {
            "模型": "deepseek-reasoner",
            "理由": "剧本改编是核心任务，需要创意+逻辑推理（心理活动外化、环境描写转音效），reasoner深度思考能力强"
        },
        "VoiceDesigner": {
            "模型": "qwen-turbo",
            "理由": "音色设计基于规则库匹配（年龄→音调，性格→语速），不需要深度推理，turbo快速响应"
        },
        "SoundEffectDesigner": {
            "模型": "qwen-turbo",
            "理由": "音效设计是场景→音效库的匹配任务（雨天→rain.mp3），规则为主，turbo即可"
        },
        "MusicComposer": {
            "模型": "qwen-turbo",
            "理由": "音乐设计主要是情绪匹配（紧张→tense_music），规则简单，turbo快速完成"
        },
        "AudioQualityReviewer": {
            "模型": "deepseek-reasoner",
            "理由": "质量评审需要多维度分析（剧本自然度、音频平衡、节奏），reasoner严谨全面"
        }
    }
    
    for agent, info in reasons.items():
        print(f"【{agent}】")
        print(f"  推荐模型: {info['模型']}")
        print(f"  选择理由: {info['理由']}\n")
    
    print("="*70)
    print("✅ 模型配置测试完成")
    print("="*70)


def test_cost_estimation():
    """测试成本估算"""
    print("\n" + "="*70)
    print("💰 成本估算对比")
    print("="*70 + "\n")
    
    # 假设价格（每百万token）
    prices = {
        "deepseek-reasoner": {"input": 1.0, "output": 4.0},  # 推理模型较贵
        "deepseek-chat": {"input": 0.2, "output": 0.8},       # chat便宜
        "qwen-max": {"input": 0.4, "output": 1.2},
        "qwen3-max": {"input": 0.4, "output": 1.2},
        "qwen-turbo": {"input": 0.1, "output": 0.3},          # turbo最便宜
        "qwen-long": {"input": 0.05, "output": 0.2},
    }
    
    # 假设每个Agent的token使用（input + output）
    token_usage = {
        "AudioDirector": (500, 200),        # 策略制定，较少token
        "AudiobookScriptAdapter": (3000, 2000),  # 剧本改编，大量token
        "VoiceDesigner": (300, 100),
        "SoundEffectDesigner": (300, 100),
        "MusicComposer": (300, 100),
        "AudioQualityReviewer": (1000, 500),
    }
    
    optimizer_conservative = get_model_optimizer("conservative")
    optimizer_aggressive = get_model_optimizer("aggressive")
    
    tasks_map = {
        "AudioDirector": TaskType.AUDIOBOOK_DIRECTOR,
        "AudiobookScriptAdapter": TaskType.AUDIOBOOK_SCRIPT,
        "VoiceDesigner": TaskType.AUDIOBOOK_VOICE,
        "SoundEffectDesigner": TaskType.AUDIOBOOK_SOUND,
        "MusicComposer": TaskType.AUDIOBOOK_MUSIC,
        "AudioQualityReviewer": TaskType.AUDIOBOOK_REVIEW,
    }
    
    total_conservative = 0
    total_aggressive = 0
    
    print("【保守策略成本】\n")
    for agent, task_type in tasks_map.items():
        model = optimizer_conservative.select_model(task_type)
        input_tokens, output_tokens = token_usage[agent]
        
        cost = (input_tokens / 1_000_000 * prices[model]["input"] + 
                output_tokens / 1_000_000 * prices[model]["output"])
        total_conservative += cost
        
        print(f"{agent:25} {model:18} ¥{cost:.4f}")
    
    print(f"\n{'总计':25} {'':18} ¥{total_conservative:.4f}")
    
    print("\n【激进策略成本】\n")
    for agent, task_type in tasks_map.items():
        model = optimizer_aggressive.select_model(task_type)
        input_tokens, output_tokens = token_usage[agent]
        
        cost = (input_tokens / 1_000_000 * prices[model]["input"] + 
                output_tokens / 1_000_000 * prices[model]["output"])
        total_aggressive += cost
        
        print(f"{agent:25} {model:18} ¥{cost:.4f}")
    
    print(f"\n{'总计':25} {'':18} ¥{total_aggressive:.4f}")
    
    savings = total_conservative - total_aggressive
    savings_pct = (savings / total_conservative * 100) if total_conservative > 0 else 0
    
    print(f"\n节省成本: ¥{savings:.4f} ({savings_pct:.1f}%)")
    print("\n" + "="*70)


if __name__ == "__main__":
    test_audiobook_model_allocation()
    test_cost_estimation()
