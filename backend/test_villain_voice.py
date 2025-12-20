"""测试反派音色分配功能"""
import sys
from pathlib import Path

# 添加项目根目录到系统路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.services.audiobook.voice_manager import VoiceManager
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def test_villain_voices():
    """测试反派音色分配"""
    manager = VoiceManager()
    
    logger.info("\n" + "="*60)
    logger.info("🎭 反派音色测试")
    logger.info("="*60)
    
    # 测试用例：不同类型的反派角色
    test_cases = [
        {
            "name": "冷血杀手",
            "info": {
                "gender": "male",
                "age_group": "adult",
                "personality": "cold",
                "role_type": "反派"
            }
        },
        {
            "name": "腹黑反派",
            "info": {
                "gender": "male",
                "age_group": "adult",
                "personality": "sinister",
                "role_type": "villain"
            }
        },
        {
            "name": "霸道总裁",
            "info": {
                "gender": "male",
                "age_group": "adult",
                "personality": "domineering",
                "role_type": "boss"
            }
        },
        {
            "name": "蛇蝎美人",
            "info": {
                "gender": "female",
                "age_group": "adult",
                "personality": "cold",
                "role_type": "反派"
            }
        },
        {
            "name": "狡诈女配",
            "info": {
                "gender": "female",
                "age_group": "adult",
                "personality": "cunning",
                "role_type": "antagonist"
            }
        },
        # 对比：正派角色（不应该分配反派音色）
        {
            "name": "正义英雄",
            "info": {
                "gender": "male",
                "age_group": "adult",
                "personality": "calm",
                "role_type": "主角"
            }
        },
        {
            "name": "温柔女主",
            "info": {
                "gender": "female",
                "age_group": "young",
                "personality": "gentle",
                "role_type": "女主"
            }
        }
    ]
    
    for case in test_cases:
        logger.info(f"\n{'─'*60}")
        logger.info(f"📝 角色: {case['name']}")
        logger.info(f"   属性: {case['info']}")
        
        # 分配音色
        profile = manager.assign_voice(
            character_name=case['name'],
            character_info=case['info']
        )
        
        logger.info(f"✅ 分配音色: {profile.voice_id}")
        logger.info(f"   TTS ID: {profile.tts_speaker_id}")
        logger.info(f"   默认情感: {profile.default_emotion}")
        
        # 测试TTS参数（不指定情感，应自动使用default_emotion）
        params_default = profile.get_tts_params()
        logger.info(f"   默认参数: pitch={params_default['pitch']}, speed={params_default['speed']:.2f}, volume={params_default['volume']}")
        
        # 测试TTS参数（指定happy情感，应覆盖default_emotion）
        params_happy = profile.get_tts_params("happy")
        logger.info(f"   开心参数: pitch={params_happy['pitch']}, speed={params_happy['speed']:.2f}, volume={params_happy['volume']}")
    
    logger.info(f"\n{'='*60}")
    logger.info("📊 音色使用统计")
    logger.info("="*60)
    stats = manager.get_statistics()
    for key, value in stats.items():
        logger.info(f"   {key}: {value}")
    
    logger.info(f"\n{'='*60}")
    logger.info("✅ 测试完成")
    logger.info("="*60)


if __name__ == "__main__":
    test_villain_voices()
