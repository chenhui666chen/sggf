"""
记忆管理模型
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.db.base import Base


class Memory(Base):
    """记忆表 - 存储对话历史和上下文"""
    __tablename__ = "memories"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, 
        ForeignKey("projects.id", ondelete="CASCADE"),  # 添加级联删除
        nullable=False, 
        index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # 对话消息（JSON格式存储）
    messages = Column(JSON, nullable=True, comment="对话历史，JSON数组格式")
    
    # 写作上下文信息
    current_chapter = Column(Integer, nullable=True, comment="当前章节编号")
    current_scene = Column(String(255), nullable=True, comment="当前场景")
    active_characters = Column(JSON, nullable=True, comment="活跃人物列表")
    writing_goal = Column(Text, nullable=True, comment="写作目标")
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<Memory project_id={self.project_id}>"
