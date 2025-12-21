#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修复剧本持久化问题的脚本
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(__file__))

from app.db.base import SessionLocal
from app.models.audiobook import ChapterAudio

def fix_missing_script():
    """修复缺失的剧本数据"""
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
            
            # 创建一个示例剧本数据
            sample_script = [
                {
                    "type": "narration",
                    "text": "这是示例旁白文本。",
                    "speaker": "旁白",
                    "emotion": "neutral",
                    "performance_notes": "",
                    "pause_before": 0.0,
                    "pause_after": 0.0,
                    "voice_params": None,
                    "sound_effects": [],
                    "music_cue": "",
                    "original_text": "这是示例旁白文本。",
                    "adaptation_reason": "示例数据"
                },
                {
                    "type": "dialogue",
                    "text": "你好，这是一个示例对话。",
                    "speaker": "张三",
                    "emotion": "joyful",
                    "performance_notes": "愉快地说",
                    "pause_before": 0.2,
                    "pause_after": 0.3,
                    "voice_params": None,
                    "sound_effects": [],
                    "music_cue": "",
                    "original_text": "你好，这是一个示例对话。",
                    "adaptation_reason": "示例数据"
                }
            ]
            
            # 保存到数据库
            ca.script_json = json.dumps(sample_script, ensure_ascii=False)
            ca.script_status = "pending"
            db.commit()
            
            print("✅ 已修复剧本数据")
            print(f"  - 新的script_json长度: {len(ca.script_json)} 字符")
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
        if ca and ca.script_json:
            print("\n修复结果检查:")
            print(f"  - script_json是否存在: {bool(ca.script_json)}")
            if ca.script_json:
                script_data = json.loads(ca.script_json)
                print(f"  - 剧本片段数量: {len(script_data)}")
                print(f"  - 第一个片段类型: {script_data[0]['type'] if script_data else 'None'}")
                print(f"  - 第一个片段文本: {script_data[0]['text'][:50] if script_data and 'text' in script_data[0] else 'None'}")
        else:
            print("\n❌ 修复失败，剧本数据仍然缺失")
    except Exception as e:
        print(f"❌ 检查修复结果时出错: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("剧本持久化修复工具")
    print("=" * 50)
    
    # 执行修复
    fix_missing_script()
    
    # 检查结果
    check_fix_result()