from __future__ import annotations

import asyncio
import logging
import time
import math
import json
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from dataclasses import asdict, is_dataclass

from ..script_adapter import AudiobookScriptAgent, ScriptSegment, ChapterStructure
from ..voice_manager_factory import create_voice_manager
from ..audio_mixer import AudioMixer
from app.services.chapter_adaptation_assets import build_audio_adaptation_hint
from app.services.audiobook.tts_cost_utils import parse_tts_cost_yuan
from core.unified_media_runtime import create_tts_engine

try:
    from app.websocket.manager import ws_manager
    WEBSOCKET_AVAILABLE = True
except Exception:  # pragma: no cover - WebSocket is optional for generation workers.
    ws_manager = None
    WEBSOCKET_AVAILABLE = False

try:
    from ..agent_dispatch_client import client as tts_dispatch_client
    from ..agent_dispatch_client import TTSDispatchResult
    TTS_DISPATCH_AVAILABLE = True
except ImportError:
    TTS_DISPATCH_AVAILABLE = False
    tts_dispatch_client = None
    TTSDispatchResult = None

# 导入专业Agent
from ..agents import (
    AudioDirector,
    SoundEffectDesigner,
    MusicComposer,
)

logger = logging.getLogger(__name__)

class ProjectMixin:
    async def generate_project_audio(
        self,
        project_id: int,
        chapter_ids: List[int],
        db_session,
        output_dir: str = "audiobooks"
    ) -> Dict[str, Any]:
        """
        生成整本书的有声书
        
        Args:
            project_id: 项目ID
            chapter_ids: 章节ID列表
            db_session: 数据库会话
            output_dir: 输出目录
        
        Returns:
            生成结果统计
        """
        logger.info(f"📚 开始生成项目 {project_id} 的有声书")
        logger.info(f"   共 {len(chapter_ids)} 章")
        
        # 1. 获取项目角色列表
        character_list = await self._get_project_characters(project_id, db_session)
        logger.info(f"   角色列表: {character_list}")
        
        # 2. 逐章生成
        results = []
        total_duration = 0
        total_size = 0
        
        for i, chapter_id in enumerate(chapter_ids, 1):
            logger.info(f"\n{'='*70}")
            logger.info(f"处理进度: {i}/{len(chapter_ids)}")
            
            # 获取章节内容
            chapter = await self._get_chapter_content(chapter_id, db_session)
            if not chapter:
                logger.warning(f"⚠️ 章节 {chapter_id} 不存在")
                continue
            
            # 生成音频
            output_path = f"{output_dir}/project_{project_id}/chapter_{chapter['number']:03d}.mp3"
            result = await self.generate_chapter_audio(
                chapter_content=chapter["content"],
                chapter_id=chapter_id,
                character_list=character_list,
                output_path=output_path,
                chapter_title=chapter.get("title") or "",
                chapter_summary=chapter.get("summary") or "",
                summary_data=chapter.get("summary_data"),
            )
            
            if result["success"]:
                total_duration += result["duration"]
                total_size += result["file_size"]
                results.append({
                    "chapter_id": chapter_id,
                    "chapter_number": chapter["number"],
                    "success": True,
                    "audio_path": output_path,
                    "duration": result["duration"]
                })
            else:
                results.append({
                    "chapter_id": chapter_id,
                    "chapter_number": chapter["number"],
                    "success": False,
                    "error": result.get("error")
                })
            
            # 短暂延迟，避免API限流
            await asyncio.sleep(0.5)
        
        # 3. 汇总统计
        success_count = sum(1 for r in results if r["success"])
        tts_stats = self._aggregate_tts_cost_stats()
        
        summary = {
            "project_id": project_id,
            "total_chapters": len(chapter_ids),
            "success_count": success_count,
            "failed_count": len(chapter_ids) - success_count,
            "total_duration": total_duration,
            "total_duration_formatted": f"{total_duration/3600:.1f}小时",
            "total_size": total_size,
            "total_size_formatted": f"{total_size/1024/1024:.1f}MB",
            "tts_stats": tts_stats,
            "results": results
        }
        
        logger.info(f"\n{'='*70}")
        logger.info(f"✅ 项目生成完成!")
        logger.info(f"   成功: {success_count}/{len(chapter_ids)}")
        logger.info(f"   总时长: {summary['total_duration_formatted']}")
        logger.info(f"   总大小: {summary['total_size_formatted']}")
        logger.info(f"   总成本: {tts_stats.get('estimated_cost', '¥0.00')}")
        logger.info(f"{'='*70}\n")
        
        return summary
    
    async def _get_project_characters(
        self,
        project_id: int,
        db_session
    ) -> List[str]:
        """获取项目角色列表"""
        try:
            from backend.app.models.character import Character
            characters = db_session.query(Character).filter(
                Character.project_id == project_id
            ).all()
            
            return [c.name for c in characters if c.name]
        except Exception as e:
            logger.warning(f"⚠️ 获取角色列表失败: {e}")
            return []
    
    async def _get_chapter_content(
        self,
        chapter_id: int,
        db_session
    ) -> Optional[Dict[str, Any]]:
        """获取章节内容"""
        try:
            from backend.app.models.project import Chapter
            chapter = db_session.query(Chapter).filter(
                Chapter.id == chapter_id
            ).first()
            
            if chapter:
                return {
                    "id": chapter.id,
                    "number": chapter.chapter_number,
                    "title": chapter.title,
                    "content": chapter.content,
                    "summary": getattr(chapter, "summary", None),
                    "summary_data": getattr(chapter, "summary_data", None),
                }
            return None
        except Exception as e:
            logger.error(f"❌ 获取章节内容失败: {e}")
            return None
    
    # ==================== 章节并行生成功能 ====================
    
    async def generate_chapters_parallel(
        self,
        chapter_list: List[Dict[str, Any]],
        audiobook_project_id: int,
        db_session,
        max_concurrent: int = 3,
        output_dir: str = "audiobooks"
    ) -> Dict[str, Any]:
        """
        并行生成多个章节的有声书（核心功能）
        
        Args:
            chapter_list: 章节列表，每个元素包含:
                - chapter_id: 章节ID
                - content: 章节内容
                - chapter_number: 章节编号
                - character_list: 角色列表
            audiobook_project_id: 有声书项目ID
            db_session: 数据库会话
            max_concurrent: 最大并发数（默认3）
            output_dir: 输出目录
        
        Returns:
            {
                "success": True/False,
                "total_chapters": int,
                "completed_chapters": int,
                "failed_chapters": int,
                "total_duration": float,
                "total_cost": float,
                "results": [...]  # 每个章节的生成结果
            }
        """
        logger.info(f"🎵 开始并行生成 {len(chapter_list)} 个章节，并发数={max_concurrent}")
        
        # 📡 推送整体进度汇总（初始状态）
        if WEBSOCKET_AVAILABLE:
            await ws_manager.send_audiobook_project_summary(
                audiobook_project_id=audiobook_project_id,
                total_chapters=len(chapter_list),
                completed_chapters=0,
                failed_chapters=0,
                total_duration=0.0,
                total_cost=0.0
            )
        
        # 使用信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # 统计数据
        results = []
        completed_count = 0
        failed_count = 0
        total_duration = 0.0
        total_cost = 0.0
        
        # 并发生成任务
        async def generate_one_chapter(chapter_info: Dict[str, Any]):
            nonlocal completed_count, failed_count, total_duration, total_cost
            
            async with semaphore:
                chapter_id = chapter_info['chapter_id']
                chapter_number = chapter_info['chapter_number']
                content = chapter_info['content']
                character_list = chapter_info.get('character_list', [])
                
                logger.info(f"  🎵 开始生成第{chapter_number}章...")
                
                try:
                    # 生成输出路径
                    output_path = f"{output_dir}/audiobook_{audiobook_project_id}/chapter_{chapter_number:03d}.mp3"
                    
                    # 调用生成方法（传递audiobook_project_id以启用WebSocket推送）
                    result = await self.generate_chapter_audio(
                        chapter_content=content,
                        chapter_id=chapter_id,
                        character_list=character_list,
                        output_path=output_path,
                        audiobook_project_id=audiobook_project_id,
                        chapter_title=chapter_info.get("title") or "",
                        chapter_summary=chapter_info.get("summary") or "",
                        summary_data=chapter_info.get("summary_data"),
                    )
                    
                    if result["success"]:
                        completed_count += 1
                        total_duration += result["duration"]
                        
                        # 提取成本
                        tts_stats = result.get("stats", {}).get("tts_stats", {})
                        raw_cost = tts_stats.get("estimated_cost_yuan")
                        if raw_cost is None:
                            raw_cost = tts_stats.get("estimated_cost", "¥0.00")
                        cost = parse_tts_cost_yuan(raw_cost) or 0.0
                        total_cost += cost
                        
                        # 📡 推送章节完成通知
                        if WEBSOCKET_AVAILABLE:
                            await ws_manager.send_audiobook_chapter_complete(
                                audiobook_project_id=audiobook_project_id,
                                chapter_id=chapter_id,
                                audio_info={
                                    "chapter_number": chapter_number,
                                    "duration": result["duration"],
                                    "file_size": result["file_size"],
                                    "output_path": output_path
                                },
                                task_id=result.get("task_id")
                            )
                        
                        results.append({
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "success": True,
                            "audio_path": output_path,
                            "duration": result["duration"],
                            "file_size": result["file_size"]
                        })
                        
                        logger.info(f"  ✅ 第{chapter_number}章生成完成: {result['duration']:.1f}秒")
                    else:
                        failed_count += 1
                        error = result.get("error", "未知错误")
                        
                        # 📡 推送章节失败通知
                        if WEBSOCKET_AVAILABLE:
                            await ws_manager.send_audiobook_chapter_error(
                                audiobook_project_id=audiobook_project_id,
                                chapter_id=chapter_id,
                                error=error,
                                task_id=result.get("task_id")
                            )
                        
                        results.append({
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "success": False,
                            "error": error
                        })
                        
                        logger.error(f"  ❌ 第{chapter_number}章生成失败: {error}")
                    
                    # 📡 推送整体进度汇总
                    if WEBSOCKET_AVAILABLE:
                        await ws_manager.send_audiobook_project_summary(
                            audiobook_project_id=audiobook_project_id,
                            total_chapters=len(chapter_list),
                            completed_chapters=completed_count,
                            failed_chapters=failed_count,
                            total_duration=total_duration,
                            total_cost=total_cost
                        )
                    
                except Exception as e:
                    failed_count += 1
                    logger.error(f"  ❌ 第{chapter_number}章生成异常: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # 📡 推送章节失败通知
                    if WEBSOCKET_AVAILABLE:
                        await ws_manager.send_audiobook_chapter_error(
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                            error=str(e)
                        )
                    
                    results.append({
                        "chapter_id": chapter_id,
                        "chapter_number": chapter_number,
                        "success": False,
                        "error": str(e)
                    })
                
                # 等待一小段时间，避免API频率限制
                await asyncio.sleep(0.5)
        
        # 并发执行所有章节
        await asyncio.gather(*[generate_one_chapter(chapter_info) for chapter_info in chapter_list])
        
        # 汇总统计
        summary = {
            "success": failed_count == 0,
            "total_chapters": len(chapter_list),
            "completed_chapters": completed_count,
            "failed_chapters": failed_count,
            "total_duration": total_duration,
            "total_duration_formatted": f"{total_duration/3600:.1f}小时" if total_duration >= 3600 else f"{total_duration/60:.1f}分钟",
            "total_cost": total_cost,
            "results": results
        }
        
        logger.info(f"\n{'='*70}")
        logger.info(f"✅ 并行生成完成!")
        logger.info(f"   成功: {completed_count}/{len(chapter_list)}")
        logger.info(f"   失败: {failed_count}")
        logger.info(f"   总时长: {summary['total_duration_formatted']}")
        logger.info(f"   总成本: ￥{total_cost:.2f}")
        logger.info(f"{'='*70}\n")
        
        return summary
