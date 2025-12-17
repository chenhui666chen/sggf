"""临时脚本：添加task_id列到chapter_audios表"""
from app.db.base import engine
from sqlalchemy import text

with engine.connect() as conn:
    # 添加task_id列
    conn.execute(text("ALTER TABLE chapter_audios ADD COLUMN task_id VARCHAR(100)"))
    conn.commit()
    print("✅ task_id列添加成功")
