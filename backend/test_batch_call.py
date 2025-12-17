"""Test if batch code is being called"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def test():
    from app.services.audiobook.engine import AudiobookEngine
    
    # Create engine
    engine = AudiobookEngine(enable_cache=False, max_concurrent=1)
    
    # Create test chapter
    chapter_content = "测试文本。" * 5
    
    print("\n" + "="*70)
    print("Testing AudiobookEngine.generate_chapter_audio")
    print("="*70)
    print(f"Chapter content length: {len(chapter_content)}")
    print("Starting generation...")
    print("="*70 + "\n")
    
    # Call generation
    result = await engine.generate_chapter_audio(
        chapter_content=chapter_content,
        chapter_id=999,
        character_list=[],
        novel_genre="测试",
        novel_theme="测试",
        enable_quality_review=False
    )
    
    print("\n" + "="*70)
    print("Result:")
    print(f"Success: {result['success']}")
    print(f"Audio size: {len(result.get('audio_data', b''))} bytes")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(test())
