"""诊断旁白音色不一致问题"""
import sys
from pathlib import Path
import json

# 添加项目根目录到系统路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.script_adapter import ScriptSegment, ChapterOpening, ChapterClosing, ChapterStructure
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def diagnose_narrator_assignment():
    """诊断旁白音色分配逻辑"""
    
    logger.info("\n" + "="*70)
    logger.info("🔍 旁白音色诊断工具")
    logger.info("="*70)
    
    # 初始化VoiceManager
    manager = VoiceManager()
    
    # 测试场景1：直接获取旁白音色
    logger.info("\n【测试1】直接获取旁白音色")
    narrator_voice = manager.get_narrator_voice()
    logger.info(f"  音色ID: {narrator_voice.voice_id}")
    logger.info(f"  TTS Speaker: {narrator_voice.tts_speaker_id}")
    logger.info(f"  描述: {manager.PRESET_VOICES[narrator_voice.voice_id]['description']}")
    
    # 测试场景2：模拟片头旁白
    logger.info("\n【测试2】模拟片头旁白分配")
    opening = ChapterOpening(
        intro_text="本章介绍测试",
        intro_narrator="旁白"  # 默认值
    )
    
    intro_speaker = getattr(opening, "intro_narrator", "旁白") or "旁白"
    logger.info(f"  片头speaker: {intro_speaker}")
    
    intro_voice = manager.get_voice(intro_speaker)
    if not intro_voice:
        logger.info("  ⚠️ 未找到已分配音色，使用默认旁白音色")
        intro_voice = manager.get_narrator_voice()
    
    logger.info(f"  音色ID: {intro_voice.voice_id}")
    logger.info(f"  TTS Speaker: {intro_voice.tts_speaker_id}")
    
    # 测试场景3：模拟片尾旁白
    logger.info("\n【测试3】模拟片尾旁白分配")
    closing = ChapterClosing(
        recap_text="本章回顾测试",
        outro_narrator="旁白"  # 默认值
    )
    
    outro_speaker = getattr(closing, "outro_narrator", "旁白") or "旁白"
    logger.info(f"  片尾speaker: {outro_speaker}")
    
    outro_voice = manager.get_voice(outro_speaker)
    if not outro_voice:
        logger.info("  ⚠️ 未找到已分配音色，使用默认旁白音色")
        outro_voice = manager.get_narrator_voice()
    
    logger.info(f"  音色ID: {outro_voice.voice_id}")
    logger.info(f"  TTS Speaker: {outro_voice.tts_speaker_id}")
    
    # 测试场景4：模拟正文旁白
    logger.info("\n【测试4】模拟正文旁白分配")
    body_segment = ScriptSegment(
        type="narration",
        text="这是正文旁白测试",
        speaker="旁白",
        emotion="neutral"
    )
    
    body_speaker = body_segment.speaker
    logger.info(f"  正文speaker: {body_speaker}")
    
    body_voice = manager.get_voice(body_speaker)
    if not body_voice:
        logger.info("  ⚠️ 未找到已分配音色，使用默认旁白音色")
        body_voice = manager.get_narrator_voice()
    
    logger.info(f"  音色ID: {body_voice.voice_id}")
    logger.info(f"  TTS Speaker: {body_voice.tts_speaker_id}")
    
    # 汇总对比
    logger.info("\n" + "="*70)
    logger.info("📊 音色对比汇总")
    logger.info("="*70)
    
    logger.info(f"\n直接获取旁白音色:  {narrator_voice.tts_speaker_id}")
    logger.info(f"片头旁白音色:      {intro_voice.tts_speaker_id}")
    logger.info(f"片尾旁白音色:      {outro_voice.tts_speaker_id}")
    logger.info(f"正文旁白音色:      {body_voice.tts_speaker_id}")
    
    # 检查一致性
    all_same = (
        narrator_voice.tts_speaker_id == intro_voice.tts_speaker_id == 
        outro_voice.tts_speaker_id == body_voice.tts_speaker_id
    )
    
    if all_same:
        logger.info("\n✅ 所有旁白音色一致")
    else:
        logger.info("\n❌ 旁白音色不一致！")
        logger.info("   可能原因：")
        logger.info("   1. VoiceManager 未正确初始化")
        logger.info("   2. 片头/片尾/正文使用了不同的 narrator 字段值")
        logger.info("   3. 用户手动配置了不同的旁白音色")


def check_preset_voices():
    """检查预设音色库中的旁白音色"""
    
    logger.info("\n" + "="*70)
    logger.info("🎵 预设音色库中的旁白音色")
    logger.info("="*70)
    
    manager = VoiceManager()
    
    # 查找所有可能的旁白音色
    narrator_voices = []
    for voice_id, config in manager.PRESET_VOICES.items():
        desc = config.get("description", "")
        if "旁白" in desc or "narrator" in voice_id.lower():
            narrator_voices.append((voice_id, config))
    
    logger.info(f"\n找到 {len(narrator_voices)} 个旁白相关音色：\n")
    
    for voice_id, config in narrator_voices:
        logger.info(f"  音色ID: {voice_id}")
        logger.info(f"    TTS Speaker: {config['tts_speaker_id']}")
        logger.info(f"    描述: {config['description']}")
        logger.info(f"    性别: {config['gender']}")
        logger.info("")


def suggest_solutions():
    """建议解决方案"""
    
    logger.info("\n" + "="*70)
    logger.info("💡 解决方案建议")
    logger.info("="*70)
    
    logger.info("""
1. **统一旁白音色配置**
   - 确保片头、片尾、正文都使用相同的 speaker 字段值
   - 推荐使用固定值 "旁白"

2. **检查用户配置**
   - 查看前端是否允许用户为"旁白"配置不同的音色
   - 确认项目级音色配置是否正确保存和加载

3. **脚本生成检查**
   - 检查 LLM 生成的脚本中，intro_narrator 和 outro_narrator 是否被修改
   - 确认正文片段的 speaker 字段是否统一使用 "旁白"

4. **代码修复建议**
   - 在 engine.py 的 _flatten_chapter_structure 方法中
   - 强制片头/片尾使用固定的旁白音色
   - 或者在 VoiceManager 中添加旁白音色缓存机制

5. **调试日志**
   - 在 TTS 合成前，输出每个片段的 speaker 和 voice_id
   - 检查是否有片段使用了非预期的音色
""")


if __name__ == "__main__":
    logger.info("开始诊断旁白音色一致性问题...\n")
    
    diagnose_narrator_assignment()
    check_preset_voices()
    suggest_solutions()
    
    logger.info("\n" + "="*70)
    logger.info("✅ 诊断完成")
    logger.info("="*70)
