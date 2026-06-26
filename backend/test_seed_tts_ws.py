#!/usr/bin/env python3
"""Test Seed-TTS WebSocket connection"""
import asyncio
import os

async def test_websocket():
    """Test Seed-TTS WebSocket synthesis"""
    from app.services.audiobook.tts_engine_pkg._aliyun_mixin import AliyunTtsMixin
    
    # Get API key from environment
    api_key = os.getenv('VOLCENGINE_TTS_API_KEY')
    if not api_key:
        print("ERROR: VOLCENGINE_TTS_API_KEY not set")
        return
    
    # Create mixin instance
    mixin = AliyunTtsMixin()
    
    # Test parameters
    text = "你好，这是一个WebSocket测试。"
    voice = "zh_female_vv_uranus_bigtts"
    model = "seed-tts-2.0-expressive"
    
    voice_params = {
        "format": "mp3",
        "sample_rate": 24000,
        "speed": 1.0,
        "volume": 50,
        "pitch": 50,
    }
    
    try:
        print(f"Testing Seed-TTS WebSocket...")
        print(f"  Text: {text}")
        print(f"  Voice: {voice}")
        print(f"  Model: {model}")
        
        # Call WebSocket method
        audio_data = await mixin._call_seed_tts_websocket(
            model=model,
            api_key=api_key,
            text=text,
            voice=voice,
            voice_params=voice_params,
        )
        
        print(f"\n✓ SUCCESS!")
        print(f"  Audio size: {len(audio_data)} bytes")
        
        # Save to file for verification
        output_file = "test_seed_tts_websocket.mp3"
        with open(output_file, "wb") as f:
            f.write(audio_data)
        print(f"  Saved to: {output_file}")
        
    except Exception as e:
        print(f"\n✗ FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_websocket())
