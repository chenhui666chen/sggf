"""
有声小说专业Agent使用示例

演示如何使用6个专业Agent创建高质量的有声剧本
"""

import asyncio
from app.services.audiobook.agents import (
    AudioDirector,
    VoiceDesigner,
    SoundEffectDesigner,
    MusicComposer,
    AudioQualityReviewer
)
from app.services.audiobook.script_adapter import AudiobookScriptAgent


async def example_full_workflow():
    """完整的有声剧本创作流程示例"""
    
    print("="*70)
    print("[Stage] 有声剧本创作完整流程演示")
    print("="*70 + "\n")
    
    # ============ 阶段1：制定改编策略 ============
    print("【阶段1】制定改编策略\n")
    
    director = AudioDirector()
    strategy = director.formulate_strategy(
        novel_genre="科幻",
        novel_theme="记忆交易的未来世界",
        target_audience="20-35岁科幻爱好者"
    )
    
    print(f"改编风格: {strategy.style.value}")
    print(f"音效密度: {strategy.sound_effect_density}")
    print(f"音乐密度: {strategy.music_density}\n")
    
    # ============ 阶段2：任务分配 ============
    print("【阶段2】任务分配\n")
    
    tasks = director.assign_tasks(project_info={
        "project_id": 1,
        "chapter_count": 10
    })
    
    for task in tasks:
        print(f"✓ {task.agent_name}: {task.task_description}")
    print()
    
    # ============ 阶段3：剧本改编 ============
    print("【阶段3】剧本改编（需要LLM）\n")
    
    # 注意：AudiobookScriptAgent必须提供llm_client
    # 以下仅为示例，实际使用时需要真实的LLM客户端
    print("⚠️  剧本改编需要LLM客户端，此处略过")
    print("   实际使用请使用: AudiobookScriptAgent(llm_client=your_llm_client)")
    print()
    
    # ============ 阶段4：音色设计 ============
    print("【阶段4】角色音色设计\n")
    
    voice_designer = VoiceDesigner()
    
    characters = [
        {"name": "林墨", "gender": "male", "age": 28, "personality": "冷静、理性", "background": "科研人员"},
        {"name": "艾琳", "gender": "female", "age": 25, "personality": "活泼、好奇", "background": "记者"}
    ]
    
    profiles = voice_designer.batch_design(characters)
    
    for name, profile in profiles.items():
        print(f"✓ {name}:")
        print(f"  音色: {profile.tts_params.speaker}")
        print(f"  描述: {profile.voice_description}")
    print()
    
    # ============ 阶段5：音效设计 ============
    print("【阶段5】音效设计\n")
    
    sound_designer = SoundEffectDesigner()
    
    script_with_effects = [
        {
            "text": "林墨走在雨中的街道上",
            "sound_effects": ["rain_heavy", "footsteps"],
            "timestamp": 0.0
        },
        {
            "text": "他推开记忆交易中心的大门",
            "sound_effects": ["door_open"],
            "timestamp": 5.0
        }
    ]
    
    sound_cues = sound_designer.design_effects(script_with_effects)
    
    print(f"设计了 {len(sound_cues)} 个音效:")
    for cue in sound_cues:
        print(f"  {cue.timestamp}s: {cue.description} ({cue.effect_type.value})")
    print()
    
    # ============ 阶段6：音乐设计 ============
    print("【阶段6】音乐设计\n")
    
    music_composer = MusicComposer()
    
    chapter_structure = {
        "total_duration": 600.0,  # 10分钟
        "overall_mood": "mysterious",
        "scenes": [
            {
                "scene_id": "scene_1",
                "start_time": 0.0,
                "duration": 300.0,
                "mood": "tense",
                "is_climax": True
            }
        ]
    }
    
    music_cues = music_composer.design_music(chapter_structure)
    
    print(f"设计了 {len(music_cues)} 个音乐提示:")
    for cue in music_cues:
        print(f"  {cue.timestamp}s: {cue.description} ({cue.mood.value})")
    print()
    
    # ============ 阶段7：质量评审 ============
    print("【阶段7】质量评审\n")
    
    reviewer = AudioQualityReviewer()
    
    # 构造评审数据
    review_segments = [
        {
            "type": "narration",
            "text": "林墨的指尖划过控制台，淡蓝色全息界面泛起涟漪。",
            "speaker": "旁白",
            "emotion": "neutral",
            "performance_notes": "",
            "sound_effects": [],
            "music_cue": ""
        }
    ] * 10  # 模拟10个片段
    
    report = reviewer.review_script(review_segments)
    
    print(f"总评: {report.overall_grade} ({report.overall_score:.1f}分)")
    print(f"剧本质量:")
    print(f"  自然度: {report.script_quality['naturalness_score']:.1f}/10")
    print(f"  清晰度: {report.script_quality['clarity_score']:.1f}/10")
    print(f"音频平衡:")
    print(f"  音效: {report.audio_balance['sound_effects']}")
    print(f"  音乐: {report.audio_balance['music']}")
    print(f"修订建议: {', '.join(report.revision_suggestions)}")
    print()
    
    # ============ 阶段8：最终批准 ============
    print("【阶段8】导演最终批准\n")
    
    decision = director.final_approval(
        audiobook_project={"id": 1, "title": "记忆交易"},
        quality_report={"overall_grade": report.overall_grade}
    )
    
    print(f"决策: {decision['status']}")
    print(f"评语: {decision['comment']}")
    print()
    
    print("="*70)
    print("[Success] 完整流程演示完成！")
    print("="*70)


async def example_single_agent():
    """单独使用某个Agent的示例"""
    
    print("\n" + "="*70)
    print("🎙️ 单独使用VoiceDesigner示例")
    print("="*70 + "\n")
    
    designer = VoiceDesigner()
    
    # 设计单个角色音色
    profile = designer.design_voice({
        "name": "神秘老人",
        "gender": "male",
        "age": 70,
        "personality": "沉稳、神秘、智慧",
        "background": "隐居的智者",
        "role": "配角"
    })
    
    print(f"角色: {profile.character_name}")
    print(f"描述: {profile.voice_description}")
    print(f"TTS参数:")
    print(f"  音色ID: {profile.tts_params.speaker}")
    print(f"  音调: {profile.tts_params.pitch}")
    print(f"  语速: {profile.tts_params.speed}")
    print(f"差异化说明: {profile.differentiation_notes}")
    print()
    
    # 获取情感调整后的参数
    tts_params_angry = designer.get_tts_params("神秘老人", emotion="angry")
    print(f"愤怒情绪下的TTS参数:")
    print(f"  音调: {tts_params_angry.pitch} (基础:{profile.tts_params.pitch}, +10)")
    print(f"  音量: {tts_params_angry.volume} (基础:{profile.tts_params.volume}, +10)")


async def main():
    """主函数"""
    # 完整流程演示
    await example_full_workflow()
    
    # 单Agent演示
    await example_single_agent()


if __name__ == "__main__":
    asyncio.run(main())
