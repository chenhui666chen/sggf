#!/usr/bin/env python3
"""Simple Seed-TTS WebSocket test with detailed logging"""
import asyncio
import json
import os
import sys

# Add backend to path
sys.path.insert(0, 'c:\\Users\\cuigu\\novel_writing_agent\\backend')

async def test():
    """Test Seed-TTS WebSocket"""
    import websocket
    
    # Configuration
    api_key = os.getenv('VOLCENGINE_TTS_API_KEY')
    app_key = os.getenv('VOLCENGINE_TTS_APP_KEY') or api_key  # Some APIs need separate app key
    ws_url = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    resource_id = "seed-tts-2.0"
    session_id = "test-session-123"
    
    # Build req_params
    req_params = {
        "model": "seed-tts-2.0-expressive",
        "speaker": "zh_female_vv_uranus_bigtts",
        "audio_params": {
            "format": "mp3",
            "sample_rate": 24000,
            "speech_rate": 0,
            "loudness_rate": 0,
        },
    }
    
    text = "你好，这是一个测试。"
    
    audio_chunks = []
    events = []
    error = None
    
    def on_open(ws):
        print("WebSocket opened")
        # Send StartConnection (use EventType as per docs)
        start_conn = {"EventType": "StartConnection"}
        ws.send(json.dumps(start_conn))
        print(f"Sent: {json.dumps(start_conn)}")
    
    def on_message(ws, message):
        if isinstance(message, (bytes, bytearray)):
            print(f"Received binary data: {len(message)} bytes")
            print(f"  Hex: {message[:50].hex()}")
            audio_chunks.append(bytes(message))
            return
        
        try:
            payload = json.loads(message)
            events.append(payload)
            event_type = payload.get("event_type") or payload.get("EventType")
            print(f"\nReceived event: {event_type}")
            print(f"  Full payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
            
            if event_type == "ConnectionStarted":
                # Send StartSession (use EventType as per docs)
                start_session = {
                    "EventType": "StartSession",
                    "session_id": session_id,
                    "req_params": req_params,
                }
                print(f"Sending StartSession: {json.dumps(start_session, ensure_ascii=False)[:300]}")
                ws.send(json.dumps(start_session))
            
            elif event_type == "SessionStarted":
                # Send TaskRequest (use EventType as per docs)
                task_req = {
                    "EventType": "TaskRequest",
                    "session_id": session_id,
                    "text": text,
                }
                print(f"Sending TaskRequest: {json.dumps(task_req, ensure_ascii=False)}")
                ws.send(json.dumps(task_req))
            
            elif event_type == "SessionFinished":
                # Send FinishSession (use EventType as per docs)
                finish_sess = {
                    "EventType": "FinishSession",
                    "session_id": session_id,
                }
                print(f"Sending FinishSession")
                ws.send(json.dumps(finish_sess))
            
            elif event_type == "ConnectionFinished":
                print("Connection finished, closing...")
                ws.close()
            
            elif event_type in ["SessionFailed", "ConnectionFailed"]:
                nonlocal error
                error = payload.get("payload", {}).get("message") or payload.get("message", "Unknown")
                print(f"ERROR: {error}")
                ws.close()
                
        except Exception as e:
            print(f"Error parsing message: {e}")
    
    def on_error(ws, err):
        nonlocal error
        error = str(err)
        print(f"WebSocket error: {err}")
    
    def on_close(ws, code, msg):
        print(f"WebSocket closed: code={code}, msg={msg}")
    
    # Create WebSocket (no headers needed if auth is in URL)
    ws = websocket.WebSocketApp(
        ws_url,
        header={},  # Auth is in URL parameters
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    
    print(f"\nConnecting to {ws_url}...")
    print(f"API Key: {api_key[:10]}...{api_key[-10:] if len(api_key) > 20 else api_key}")
    print(f"Resource ID: {resource_id}")
    print("-" * 80)
    
    ws.run_forever(ping_timeout=30, ping_interval=60)
    
    print("\n" + "=" * 80)
    print(f"Events received: {len(events)}")
    print(f"Audio chunks: {len(audio_chunks)}")
    print(f"Total audio size: {sum(len(c) for c in audio_chunks)} bytes")
    if error:
        print(f"Error: {error}")
    else:
        print("✓ Test completed successfully!")
    
    return len(audio_chunks) > 0

if __name__ == "__main__":
    asyncio.run(test())
