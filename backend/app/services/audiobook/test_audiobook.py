"""
有声书生成系统测试脚本

用法:
    python -m backend.app.services.audiobook.test_audiobook
"""
import asyncio
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_text_parser():
    """测试文本解析器"""
    from .text_parser import TextParser
    
    logger.info("="*70)
    logger.info("测试: 文本解析器")
    logger.info("="*70)
    
    sample_text = """
    林峰站在悬崖边，望着远处的群山，心中百感交集。
    
    "师兄，我们真的能找到传说中的神器吗？"小师妹苏若兰小声问道，语气中带着一丝担忧。
    
    林峰转过身，看着这个跟随自己三年的师妹，露出一个自信的笑容。
    
    "放心吧，"他轻声说道，"只要我们齐心协力，没有什么是不可能的。"
    
    突然，远处传来一阵巨响，震得山石摇动。两人对视一眼，脸色同时一变。
    
    "不好！"林峰大喝一声，"是魔族的人追来了！"
    
    苏若兰握紧手中的剑，平静地说："师兄，你先走，我断后。"
    
    "胡说！"林峰怒喝，"要走一起走，要留一起留！"
    """
    
    parser = TextParser()
    segments = await parser.parse_chapter(
        chapter_content=sample_text,
        character_list=["林峰", "苏若兰"]
    )
    
    logger.info(f"\n解析结果:")
    for i, seg in enumerate(segments[:10], 1):  # 只显示前10个
        logger.info(
            f"{i}. [{seg.type}] {seg.speaker} ({seg.emotion}): {seg.text[:30]}..."
        )
    
    stats = parser.get_statistics(segments)
    logger.info(f"\n统计信息: {stats}")
    
    return segments


async def test_voice_manager():
    """测试音色管理器"""
    from .voice_manager import VoiceManager
    
    logger.info("\n" + "="*70)
    logger.info("测试: 音色管理器")
    logger.info("="*70)
    
    manager = VoiceManager()
    
    # 为角色分配音色
    characters = [
        {"name": "林峰", "gender": "male", "age_group": "young", "personality": "energetic"},
        {"name": "苏若兰", "gender": "female", "age_group": "young", "personality": "gentle"},
        {"name": "老道士", "gender": "male", "age_group": "elder", "personality": "calm"}
    ]
    
    for char in characters:
        profile = manager.assign_voice(
            character_name=char["name"],
            character_info=char
        )
        logger.info(f"\n{char['name']}:")
        logger.info(f"  - 音色ID: {profile.voice_id}")
        logger.info(f"  - TTS音色: {profile.tts_speaker_id}")
        logger.info(f"  - 基础参数: 音高={profile.pitch_base}, 语速={profile.speed_base}")
        
        # 测试情感参数
        for emotion in ["neutral", "happy", "angry"]:
            params = profile.get_tts_params(emotion)
            logger.info(f"  - {emotion}: {params}")
    
    stats = manager.get_statistics()
    logger.info(f"\n统计: {stats}")


async def test_tts_engine():
    """测试TTS引擎（需要API Key）"""
    from .tts_engine import TTSEngine
    import os
    
    logger.info("\n" + "="*70)
    logger.info("测试: TTS引擎")
    logger.info("="*70)
    
    # 检查API Key
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        logger.warning("⚠️ 未配置 DASHSCOPE_API_KEY，跳过TTS测试")
        logger.info("提示: 请在环境变量中设置 DASHSCOPE_API_KEY")
        return None
    
    engine = TTSEngine(enable_cache=True, max_concurrent=3)
    
    # 测试单个合成
    test_text = "这是一段测试文本，用于验证TTS引擎是否正常工作。"
    voice_params = {
        "speaker": "zhixiaobao",
        "pitch": 50,
        "speed": 1.0,
        "volume": 50
    }
    
    logger.info(f"合成文本: {test_text}")
    audio_data = await engine.synthesize(test_text, voice_params)
    
    if audio_data:
        logger.info(f"✅ 合成成功: {len(audio_data)} 字节")
        
        # 保存测试音频
        test_file = "test_audio.mp3"
        with open(test_file, 'wb') as f:
            f.write(audio_data)
        logger.info(f"💾 测试音频已保存: {test_file}")
    else:
        logger.error("❌ 合成失败")
    
    # 测试批量合成
    batch_segments = [
        {"text": "第一段文本", "voice_params": voice_params, "emotion": "neutral"},
        {"text": "第二段文本，带有情感", "voice_params": voice_params, "emotion": "happy"},
        {"text": "第三段文本", "voice_params": voice_params, "emotion": "calm"}
    ]
    
    logger.info(f"\n批量合成测试: {len(batch_segments)} 个片段")
    audio_list = await engine.synthesize_batch(batch_segments)
    logger.info(f"✅ 批量合成完成: {len([a for a in audio_list if a])} 成功")
    
    # 成本统计
    stats = engine.get_cost_stats()
    logger.info(f"\n成本统计: {stats}")
    
    return audio_list


async def test_audio_mixer(audio_list):
    """测试音频混合器"""
    from .audio_mixer import AudioMixer
    
    logger.info("\n" + "="*70)
    logger.info("测试: 音频混合器")
    logger.info("="*70)
    
    if not audio_list or not any(audio_list):
        logger.warning("⚠️ 没有可用的音频数据，跳过混合测试")
        return None
    
    mixer = AudioMixer(silence_duration=500)
    
    # 混合音频
    final_audio = mixer.mix_chapter(audio_list)
    
    if final_audio:
        logger.info(f"✅ 混合成功: {len(final_audio)} 字节")
        
        # 保存
        test_file = "test_chapter.mp3"
        with open(test_file, 'wb') as f:
            f.write(final_audio)
        logger.info(f"💾 章节音频已保存: {test_file}")
        
        # 获取信息
        info = mixer.get_audio_info(final_audio)
        logger.info(f"音频信息: {info}")
    else:
        logger.error("❌ 混合失败")
    
    return final_audio


async def test_complete_workflow():
    """测试完整工作流"""
    from .engine import AudiobookEngine
    
    logger.info("\n" + "="*70)
    logger.info("测试: 完整工作流")
    logger.info("="*70)
    
    sample_chapter = """
    第一章 启程
    
    清晨的阳光透过窗户，洒在林峰的脸上。他缓缓睁开眼睛，新的一天开始了。
    
    "师兄，该起来修炼了！"门外传来苏若兰清脆的声音。
    
    林峰揉了揉眼睛，笑道："知道了，马上就来。"
    
    他穿好衣服，走出房间。苏若兰已经在院子里等候多时。
    
    "今天我们要去哪里？"苏若兰问道，眼中闪烁着期待的光芒。
    
    "听说东边的迷雾森林里有异宝出世，"林峰沉声说道，"我们去看看。"
    
    两人整理好行囊，踏上了征途。未知的危险在等待着他们，但他们并不畏惧。
    
    因为，这就是修行者的宿命。
    """
    
    engine = AudiobookEngine(enable_cache=True)
    
    result = await engine.generate_chapter_audio(
        chapter_content=sample_chapter,
        chapter_id=1,
        character_list=["林峰", "苏若兰"],
        output_path="test_complete_chapter.mp3"
    )
    
    if result["success"]:
        logger.info(f"\n✅ 完整测试成功!")
        logger.info(f"统计: {result['stats']}")
    else:
        logger.error(f"\n❌ 完整测试失败: {result.get('error')}")


async def main():
    """主测试函数"""
    logger.info("🎙️ 有声书生成系统测试")
    logger.info("="*70)
    
    # 1. 测试文本解析
    segments = await test_text_parser()
    
    # 2. 测试音色管理
    await test_voice_manager()
    
    # 3. 测试TTS引擎
    audio_list = await test_tts_engine()
    
    # 4. 测试音频混合
    if audio_list:
        await test_audio_mixer(audio_list)
    
    # 5. 测试完整工作流
    # await test_complete_workflow()  # 取消注释以运行完整测试
    
    logger.info("\n" + "="*70)
    logger.info("✅ 所有测试完成!")
    logger.info("="*70)


if __name__ == "__main__":
    asyncio.run(main())
