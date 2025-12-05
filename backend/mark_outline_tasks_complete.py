"""将所有大纲扩展任务标记为已完成"""
from app.db.base import engine
from sqlalchemy import text

def mark_outline_tasks_complete():
    """标记所有大纲扩展任务为已完成"""
    with engine.connect() as conn:
        # 查询所有大纲扩展任务
        result = conn.execute(text("""
            SELECT task_id, task_type, status, created_at 
            FROM generation_history 
            WHERE task_type LIKE '%outline%'
            ORDER BY created_at DESC
        """))
        
        tasks = result.fetchall()
        
        if not tasks:
            print("❌ 未找到任何大纲扩展任务")
            return
        
        print(f"📋 找到 {len(tasks)} 个大纲扩展任务:\n")
        for task in tasks:
            print(f"  - {task[0][:40]}... | {task[1]} | 状态: {task[2]} | {task[3]}")
        
        # 更新所有大纲扩展任务为已完成
        update_result = conn.execute(text("""
            UPDATE generation_history 
            SET status = 'completed',
                completed_at = datetime('now')
            WHERE task_type LIKE '%outline%'
              AND status != 'completed'
        """))
        
        conn.commit()
        
        updated_count = update_result.rowcount
        print(f"\n✅ 成功将 {updated_count} 个大纲扩展任务标记为已完成")
        
        # 验证更新
        verify_result = conn.execute(text("""
            SELECT COUNT(*) 
            FROM generation_history 
            WHERE task_type LIKE '%outline%' AND status = 'completed'
        """))
        
        completed_count = verify_result.scalar()
        print(f"🔍 验证: 当前有 {completed_count} 个已完成的大纲扩展任务")

if __name__ == "__main__":
    mark_outline_tasks_complete()
