"""测试人物文本生成服务"""
from app.db.base import SessionLocal
from app.services.character_text_generator import CharacterTextGenerator
from app.models.character import Character

db = SessionLocal()
try:
    # 获取第一个有人物的项目
    char = db.query(Character).first()
    if char:
        print(f'找到项目 {char.project_id} 的人物: {char.name}')
        print('='*50)
        # 生成单个人物文本
        text = CharacterTextGenerator.generate_single_character_text(char, db)
        print(text)
        print('='*50)
        # 获取统计
        stats = CharacterTextGenerator.get_character_stats(char.project_id, db)
        print(f'统计: 共 {stats["total"]} 个人物')
        print(f'按重要程度: {stats["by_importance"]}')
    else:
        print('数据库中暂无人物数据，使用模拟数据测试')
        # 模拟测试
        class MockChar:
            name = "林风"
            gender = "男"
            age = 18
            role = "protagonist_side"
            importance_level = "protagonist"
            faction = "清风宗"
            current_realm = None
            faction_item = None
            profession_item = None
            race_item = None
            appearance_status = "appeared"
            life_status = "alive"
            first_appearance_chapter = 1
            character_techniques = []
            tags = '["剑修", "天才"]'
            summary = "天资聪颖的少年剑修，清风宗掌门关门弟子"
            relations = None
            profile = None
        
        text = CharacterTextGenerator.generate_single_character_text(MockChar(), db)
        print(text)
finally:
    db.close()
    print('\n✅ 测试完成')
