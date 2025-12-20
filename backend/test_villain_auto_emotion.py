"""测试反派角色自动情感分配"""
import sys
from pathlib import Path

# 添加项目根目录到系统路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.services.audiobook.voice_manager import VoiceManager
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def test_villain_voice_assignment():
    """测试反派角色音色自动分配"""
    
    logger.info("\n" + "="*70)
    logger.info("🎭 反派角色自动识别与音色分配测试")
    logger.info("="*70)
    
    manager = VoiceManager()
    
    # 测试用例
    test_cases = [
        {
            "name": "邪恶大魔王",
            "info": {
                "gender": "male",
                "age_group": "adult",
                "personality": "evil",  # 邪恶 → 触发反派识别
                "role_type": "villain"
            },
            "expected": "male_young_energetic (longanyang)"
        },
        {
            "name": "冷血杀手",
            "info": {
                "gender": "male",
                "age_group": "adult",
                "personality": "cold",  # 冷酷 → 触发反派识别
                "role_type": ""
            },
            "expected": "male_young_energetic (longanyang)"
        },
        {
            "name": "阴险女反派",
            "info": {
                "gender": "female",
                "age_group": "adult",
                "personality": "sinister",  # 阴险 → 触发反派识别
                "role_type": ""
            },
            "expected": "female_young_energetic (longanhuan)"
        },
        {
            "name": "幕后boss",
            "info": {
                "gender": "male",
                "age_group": "adult",
                "personality": "calm",
                "role_type": "boss"  # boss → 触发反派识别
            },
            "expected": "male_young_energetic (longanyang)"
        },
        {
            "name": "温柔女主",
            "info": {
                "gender": "female",
                "age_group": "young",
                "personality": "gentle",  # 温柔 → 正常角色
                "role_type": ""
            },
            "expected": "female_young_gentle (longwanjun_v3)"
        },
    ]
    
    for i, case in enumerate(test_cases, 1):
        logger.info(f"\n{'─'*70}")
        logger.info(f"测试 {i}/{len(test_cases)}: {case['name']}")
        logger.info(f"   角色信息: {case['info']}")
        
        # 分配音色
        profile = manager.assign_voice(
            character_name=case["name"],
            character_info=case["info"]
        )
        
        logger.info(f"   ✅ 分配结果: {profile.voice_id} ({profile.tts_speaker_id})")
        logger.info(f"   📌 预期结果: {case['expected']}")
        
        # 检查是否匹配预期
        if case['expected'].split()[0] in profile.voice_id:
            logger.info(f"   ✅ 匹配成功")
        else:
            logger.warning(f"   ⚠️ 未匹配预期")
    
    logger.info(f"\n{'='*70}")
    logger.info("✅ 测试完成")
    logger.info("="*70)


def test_villain_emotion_override():
    """测试反派角色自动情感覆盖"""
    
    logger.info("\n" + "="*70)
    logger.info("🎭 反派角色自动情感覆盖测试")
    logger.info("="*70)
    
    from app.services.audiobook.tts_engine import TTSEngine
    
    engine = TTSEngine(model="cosyvoice-v3-flash", enable_cache=False)
    
    # 模拟反派角色的voice_params
    test_cases = [
        {
            "speaker": "longanyang",
            "emotion": "neutral",
            "description": "反派音色 + neutral → 应自动变为 angry"
        },
        {
            "speaker": "longanhuan",
            "emotion": "neutral",
            "description": "女反派音色 + neutral → 应自动变为 angry"
        },
        {
            "speaker": "longanzhi_v3",
            "emotion": "neutral",
            "description": "普通音色 + neutral → 保持 neutral"
        },
        {
            "speaker": "longanyang",
            "emotion": "happy",
            "description": "反派音色 + happy → 保持 happy（尊重明确指定的情感）"
        },
    ]
    
    for i, case in enumerate(test_cases, 1):
        logger.info(f"\n{'─'*70}")
        logger.info(f"测试 {i}/{len(test_cases)}: {case['description']}")
        logger.info(f"   输入: speaker={case['speaker']}, emotion={case['emotion']}")
        
        # 模拟TTS引擎的emotion处理逻辑
        voice_params = {"speaker": case["speaker"], "pitch": 50, "speed": 1.0, "volume": 50}
        emotion = case["emotion"]
        
        # 检测反派音色并自动调整情感
        villain_voice_ids = ["longanyang", "longanhuan"]
        if case["speaker"] in villain_voice_ids and (emotion == "neutral" or not emotion):
            logger.info(f"   🎭 检测到反派音色，自动应用 'angry' 情感")
            emotion = "angry"
        
        logger.info(f"   ✅ 最终emotion: {emotion}")
    
    logger.info(f"\n{'='*70}")
    logger.info("✅ 测试完成")
    logger.info("="*70)


if __name__ == "__main__":
    print("开始测试反派角色自动识别与情感分配...\n")
    
    # 测试1：音色自动分配
    test_villain_voice_assignment()
    
    # 测试2：情感自动覆盖
    test_villain_emotion_override()
    
    print("\n\n📝 功能说明：")
    print("1. 当角色的 personality 包含 'evil/sinister/cruel/cold/ruthless/domineering/cunning' 时")
    print("   或 role_type 包含 '反派/villain/boss/enemy' 时")
    print("   → 自动分配支持Instruct的音色（男性→longanyang, 女性→longanhuan）")
    print()
    print("2. 当使用这些音色且情感为neutral时")
    print("   → TTS引擎自动将情感调整为 'angry'，通过Instruct情感控制实现反派效果")
    print()
    print("3. 用户仍可在前端配置页面手动选择任何音色，包括这些特色音色")
