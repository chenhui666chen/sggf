import requests
import json

resp = requests.get('https://dashscope.aliyuncs.com/compatible-mode/v1/models', headers={'Authorization':'Bearer ***REDACTED-DASHSCOPE-KEY***'})
data = resp.json()
all_models = data.get('data', [])
tts_models = [m for m in all_models if any(k in m['id'].lower() for k in ['tts','cosy','speech','minimax/speech'])]
print(f'TTS/Speech models on DashScope ({len(tts_models)}):')
for m in tts_models:
    print(f'  {m["id"]}')

# Also check mureka endpoint
print("\n\nChecking Mureka...")
try:
    r = requests.get('https://api.mureka.cn/api/v1/audio/generation', timeout=5)
    print(f"Mureka status: {r.status_code}")
    print(r.text[:500])
except Exception as e:
    print(f"Mureka error: {e}")
