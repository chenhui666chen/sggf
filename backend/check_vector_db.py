"""检查向量库中的数据"""
from app.services.agents.knowledge_base import NovelKnowledgeBase

kb = NovelKnowledgeBase()
collection = kb.vectorstore._collection

# 检查项目4的总文档数
results = collection.get(where={"project_id": "4"})
print(f"📊 项目4总文档数: {len(results['ids'])}")

# 检查人物文档
char_results = collection.get(where={"$and": [{"type": "character"}, {"project_id": "4"}]})
print(f"👤 人物文档数: {len(char_results['ids'])}")
if char_results['ids']:
    print("   人物样本:")
    for i, (doc_id, meta) in enumerate(zip(char_results['ids'][:3], char_results['metadatas'][:3])):
        print(f"   - {meta.get('name', '未知')} (ID: {doc_id[:20]}...)")

# 检查设定文档
world_results = collection.get(where={"$and": [{"type": "world_setting"}, {"project_id": "4"}]})
print(f"🌍 设定文档数: {len(world_results['ids'])}")
if world_results['ids']:
    print("   设定样本:")
    for i, (doc_id, meta) in enumerate(zip(world_results['ids'][:3], world_results['metadatas'][:3])):
        print(f"   - {meta.get('title', '未知')} (ID: {doc_id[:20]}...)")

# 检查章节文档
chapter_results = collection.get(where={"$and": [{"type": "chapter"}, {"project_id": "4"}]})
print(f"📖 章节文档数: {len(chapter_results['ids'])}")
if chapter_results['ids']:
    print("   章节样本:")
    for i, (doc_id, meta) in enumerate(zip(chapter_results['ids'][:3], chapter_results['metadatas'][:3])):
        chapter_num = meta.get('chapter_num', '?')
        title = meta.get('title', '未知')
        print(f"   - 第{chapter_num}章 {title} (ID: {doc_id[:20]}...)")

# 检查所有项目的数据分布
all_results = collection.get()
print(f"\n📊 总文档数: {len(all_results['ids'])}")
if all_results['metadatas']:
    project_ids = set()
    types = {}
    for meta in all_results['metadatas']:
        pid = meta.get('project_id', 'unknown')
        project_ids.add(pid)
        doc_type = meta.get('type', 'unknown')
        types[doc_type] = types.get(doc_type, 0) + 1
    
    print(f"   项目ID列表: {sorted(project_ids)}")
    print(f"   类型分布: {types}")
