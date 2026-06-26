#!/usr/bin/env python3
import asyncio
import httpx
import os
import json

async def test():
    api_key = os.getenv('VOLCENGINE_TTS_API_KEY')
    payload = {
        'user': {'uid': 'audiobook'},
        'req_params': {
            'model': 'seed-tts-2.0-expressive',
            'text': '测试',
            'text_type': 'plain',
            'with_timestamp': 0,
            'speaker': 'zh_female_ganmaodianyin_uranus_bigtts',
            'audio_params': {
                'format': 'mp3',
                'sample_rate': 24000,
                'speech_rate': 0,
                'loudness_rate': 0
            }
        }
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            'https://openspeech.bytedance.com/api/v3/tts/unidirectional',
            headers={
                'X-Api-App-Key': api_key,
                'X-Api-Key': api_key,
                'X-Api-Resource-Id': 'seed-tts-2.0',
                'Content-Type': 'application/json'
            },
            json=payload
        )
        
        print(f'Status: {response.status_code}')
        print(f'Content-Type: {response.headers.get("content-type")}')
        print(f'Size: {len(response.content)} bytes')
        print(f'First 500 chars: {response.text[:500]}')
        
        # 尝试解析 JSON
        try:
            data = response.json()
            print(f'\nJSON structure:')
            print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
        except:
            print('\nNot valid JSON')

asyncio.run(test())
