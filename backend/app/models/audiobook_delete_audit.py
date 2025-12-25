"""
有声书删除审计日志模型
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.base import Base


class AudiobookDeleteAudit(Base):
    """有声书删除审计日志表"""
    __tablename__ = "audiobook_delete_audits"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # 删除类型
    delete_type = Column(String(20), nullable=False)  # project | chapter_audio
    target_id = Column(Integer, nullable=False)  # 被删除的项目或章节音频ID
    
    # 用户信息
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_name = Column(String(100), nullable=True)  # 冗余字段，方便查询
    
    # 删除前数据快照
    snapshot_json = Column(JSON, nullable=True)  # 删除前的完整数据快照
    
    # 删除详情
    delete_reason = Column(Text, nullable=True)  # 删除原因（可选）
    file_count = Column(Integer, default=0)  # 删除的文件数量
    total_size = Column(Integer, default=0)  # 删除的总大小（字节）
    
    # 影响范围
    affected_chapters = Column(Integer, default=0)  # 影响的章节数
    affected_tasks = Column(Integer, default=0)  # 影响的任务数
    
    # 时间
    deleted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # 恢复信息
    restored_at = Column(DateTime, nullable=True)  # 恢复时间
    restored_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # 恢复操作者
    
    # 关系
    user = relationship("User", foreign_keys=[user_id])
    restorer = relationship("User", foreign_keys=[restored_by])
