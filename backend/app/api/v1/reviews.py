"""
评审API路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.review import Review
from app.schemas.review import ReviewCreate, ReviewUpdate, ReviewResponse
from app.core.security import get_current_user

router = APIRouter(prefix="/api/v1/chapters", tags=["reviews"])


@router.post("/{chapter_id}/review", response_model=ReviewResponse)
async def create_review(
    chapter_id: int,
    review_data: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建评审"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 删除旧的评审
    old_review = db.query(Review).filter(Review.chapter_id == chapter_id).first()
    if old_review:
        db.delete(old_review)
    
    # 创建新评审
    review = Review(
        chapter_id=chapter_id,
        overall_score=review_data.overall_score,
        story_score=review_data.story_score,
        character_score=review_data.character_score,
        language_score=review_data.language_score,
        structure_score=review_data.structure_score,
        innovation_score=review_data.innovation_score,
        feedback=review_data.feedback,
        suggestions=review_data.suggestions,
        strengths=review_data.strengths
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.get("/{chapter_id}/review", response_model=ReviewResponse)
async def get_review(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取评审"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    review = db.query(Review).filter(Review.chapter_id == chapter_id).first()
    
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )
    
    return review


@router.put("/{chapter_id}/review", response_model=ReviewResponse)
async def update_review(
    chapter_id: int,
    review_data: ReviewUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新评审"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    review = db.query(Review).filter(Review.chapter_id == chapter_id).first()
    
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )
    
    for key, value in review_data.dict(exclude_unset=True).items():
        setattr(review, key, value)
    
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.delete("/{chapter_id}/review")
async def delete_review(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除评审"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    review = db.query(Review).filter(Review.chapter_id == chapter_id).first()
    
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )
    
    db.delete(review)
    db.commit()
    return {"message": "Review deleted successfully"}

