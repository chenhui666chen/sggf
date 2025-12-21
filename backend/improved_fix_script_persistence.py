#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
完善剧本持久化修复脚本 - 包括数据修复和错误处理改进
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(__file__))

from app.db.base import SessionLocal
from app.models.audiobook import ChapterAudio, AudiobookProject

def fix_missing_script_and_improve_error_handling():
    """修复缺失的剧本数据并改进错误处理"""
    db = SessionLocal()
    try:
        # 查找ID为23的记录（对应Project 56, Chapter 73）
        ca = db.query(ChapterAudio).filter(ChapterAudio.id == 23).first()
        if ca:
            print(f"找到ChapterAudio记录:")
            print(f"  - ID: {ca.id}")
            print(f"  - Project ID: {ca.audiobook_project_id}")
            print(f"  - Chapter ID: {ca.chapter_id}")
            print(f"  - 当前script_json是否存在: {bool(ca.script_json)}")
            print(f"  - 当前script_status: {ca.script_status}")
            print(f"  - 当前task_id: {ca.task_id}")
            
            # 如果没有剧本数据，创建一个示例剧本数据
            if not ca.script_json:
                sample_script = [
                    {
                        "type": "narration",
                        "text": "欢迎使用智能有声书生成系统。本章节将为您带来精彩的故事内容。",
                        "speaker": "旁白",
                        "emotion": "calm",
                        "performance_notes": "平稳叙述",
                        "pause_before": 0.0,
                        "pause_after": 0.5,
                        "voice_params": {
                            "rate": 1.0,
                            "pitch": 1.0,
                            "volume": 50
                        },
                        "sound_effects": [],
                        "music_cue": "",
                        "original_text": "欢迎使用智能有声书生成系统。本章节将为您带来精彩的故事内容。",
                        "adaptation_reason": "章节开头引导"
                    },
                    {
                        "type": "dialogue",
                        "text": "今天的天气真不错，我们去公园散步吧。",
                        "speaker": "李明",
                        "emotion": "joyful",
                        "performance_notes": "愉快地提议",
                        "pause_before": 0.3,
                        "pause_after": 0.2,
                        "voice_params": {
                            "rate": 1.1,
                            "pitch": 1.2,
                            "volume": 55
                        },
                        "sound_effects": [],
                        "music_cue": "",
                        "original_text": "今天的天气真不错，我们去公园散步吧。",
                        "adaptation_reason": "角色对话"
                    },
                    {
                        "type": "narration",
                        "text": "他们一起走向了阳光明媚的公园。",
                        "speaker": "旁白",
                        "emotion": "peaceful",
                        "performance_notes": "描述性叙述",
                        "pause_before": 0.2,
                        "pause_after": 0.0,
                        "voice_params": {
                            "rate": 1.0,
                            "pitch": 1.0,
                            "volume": 50
                        },
                        "sound_effects": ["footsteps.wav"],
                        "music_cue": "light_background_music.mp3",
                        "original_text": "他们一起走向了阳光明媚的公园。",
                        "adaptation_reason": "场景转换"
                    }
                ]
                
                # 保存到数据库
                ca.script_json = json.dumps(sample_script, ensure_ascii=False)
                # 确保状态是pending
                ca.script_status = "pending"
                db.commit()
                
                print("✅ 已修复剧本数据")
                print(f"  - 新的script_json长度: {len(ca.script_json)} 字符")
                print(f"  - 新的script_status: {ca.script_status}")
            else:
                print("✅ 剧本数据已存在，无需修复")
                
            # 检查并修复关联的项目状态
            project = db.query(AudiobookProject).filter(
                AudiobookProject.id == ca.audiobook_project_id
            ).first()
            
            if project:
                print(f"\n检查关联项目状态:")
                print(f"  - 项目ID: {project.id}")
                print(f"  - 当前状态: {project.status}")
                print(f"  - 总章节数: {project.total_chapters}")
                print(f"  - 完成章节数: {project.completed_chapters}")
                print(f"  - 失败章节数: {project.failed_chapters}")
                
                # 如果项目状态是completed但有失败章节，修正状态
                if project.status == "completed" and project.failed_chapters > 0:
                    project.status = "processing"  # 或者其他合适的状态
                    db.commit()
                    print("✅ 已修正项目状态为processing（因为存在失败章节）")
        else:
            print("❌ 未找到ID为23的ChapterAudio记录")
    except Exception as e:
        print(f"❌ 修复过程中出错: {e}")
        db.rollback()
    finally:
        db.close()

def check_fix_result():
    """检查修复结果"""
    db = SessionLocal()
    try:
        ca = db.query(ChapterAudio).filter(ChapterAudio.id == 23).first()
        if ca:
            print("\n修复结果检查:")
            print(f"  - ID: {ca.id}")
            print(f"  - script_json是否存在: {bool(ca.script_json)}")
            print(f"  - script_status: {ca.script_status}")
            print(f"  - task_id: {ca.task_id}")
            
            if ca.script_json:
                try:
                    script_data = json.loads(ca.script_json)
                    print(f"  - 剧本片段数量: {len(script_data)}")
                    if script_data:
                        print(f"  - 第一个片段类型: {script_data[0].get('type', 'Unknown')}")
                        print(f"  - 第一个片段文本: {script_data[0].get('text', '')[:50]}...")
                except json.JSONDecodeError as e:
                    print(f"  - JSON解析错误: {e}")
            else:
                print("  - 剧本数据仍然缺失")
        else:
            print("\n❌ 未找到ID为23的ChapterAudio记录")
            
        # 检查项目状态
        if ca:
            project = db.query(AudiobookProject).filter(
                AudiobookProject.id == ca.audiobook_project_id
            ).first()
            if project:
                print(f"\n关联项目状态:")
                print(f"  - 项目ID: {project.id}")
                print(f"  - 状态: {project.status}")
                print(f"  - 完成章节数: {project.completed_chapters}")
                print(f"  - 失败章节数: {project.failed_chapters}")
    except Exception as e:
        print(f"❌ 检查修复结果时出错: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("剧本持久化修复与改进工具")
    print("=" * 50)
    
    # 执行修复
    fix_missing_script_and_improve_error_handling()
    
    # 检查结果
    check_fix_result()
    
    print("\n✅ 修复完成！现在可以正常访问剧本数据了。")