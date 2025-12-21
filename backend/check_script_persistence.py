#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查剧本持久化问题的诊断脚本
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.db.base import SessionLocal
from app.models.audiobook import ChapterAudio

def check_chapter_audio(chapter_audio_id):
    """检查指定ID的ChapterAudio记录"""
    db = SessionLocal()
    try:
        ca = db.query(ChapterAudio).filter(ChapterAudio.id == chapter_audio_id).first()
        print(f"ChapterAudio ID {chapter_audio_id} 查询结果:")
        if ca:
            print(f"  - 存在记录: True")
            print(f"  - audiobook_project_id: {ca.audiobook_project_id}")
            print(f"  - chapter_id: {ca.chapter_id}")
            print(f"  - task_id: {ca.task_id}")
            print(f"  - script_json 是否存在: {bool(ca.script_json)}")
            if ca.script_json:
                print(f"  - script_json 长度: {len(ca.script_json)} 字符")
                # 显示前200个字符
                print(f"  - script_json 内容预览: {ca.script_json[:200]}...")
            else:
                print(f"  - script_json 为空")
            print(f"  - script_status: {ca.script_status}")
            print(f"  - created_at: {ca.created_at}")
            print(f"  - updated_at: {ca.updated_at}")
        else:
            print(f"  - 存在记录: False")
    except Exception as e:
        print(f"查询出错: {e}")
    finally:
        db.close()

def list_recent_chapter_audios():
    """列出最近的ChapterAudio记录"""
    db = SessionLocal()
    try:
        records = db.query(ChapterAudio).order_by(ChapterAudio.updated_at.desc()).limit(10).all()
        print("\n最近10条ChapterAudio记录:")
        print("-" * 80)
        for ca in records:
            print(f"ID: {ca.id:3d} | Project: {ca.audiobook_project_id:2d} | Chapter: {ca.chapter_id:2d} | "
                  f"Task: {ca.task_id[:8] if ca.task_id else 'None':8} | "
                  f"Has Script: {'Yes' if ca.script_json else 'No':3} | "
                  f"Status: {ca.script_status or 'None':8} | "
                  f"Updated: {ca.updated_at.strftime('%Y-%m-%d %H:%M:%S') if ca.updated_at else 'None'}")
    except Exception as e:
        print(f"查询出错: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("剧本持久化诊断工具")
    print("=" * 50)
    
    # 检查特定ID（从错误信息中看到是73）
    check_chapter_audio(73)
    
    # 列出最近记录
    list_recent_chapter_audios()