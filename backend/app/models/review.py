"""
评审模型
"""
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base


class Review(Base):
    """评审表"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    chapter_id = Column(
        Integer,
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False
    )
    overall_score = Column(Integer, nullable=True)  # 1-10
    story_score = Column(Integer, nullable=True)
    character_score = Column(Integer, nullable=True)
    language_score = Column(Integer, nullable=True)
    structure_score = Column(Integer, nullable=True)
    innovation_score = Column(Integer, nullable=True)
    feedback = Column(Text, nullable=True)
    suggestions = Column(Text, nullable=True)
    strengths = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Review {self.chapter_id}>"

