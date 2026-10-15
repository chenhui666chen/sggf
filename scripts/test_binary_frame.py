#!/usr/bin/env python3
"""Test Seed-TTS WebSocket with binary frame protocol"""
import json
import struct
import os
import uuid
from pathlib import Path
from enum import IntEnum

import websocket

# Load environment variables
PROJECT_ROOT = Path(__file__).parent.parent
env_file = PROJECT_ROOT / ".env.local"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

# Configuration
ws_url = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
api_key = os.getenv("VOLCENGINE_TTS_API_KEY") or os.getenv("DOUBAO_TTS_API_KEY")
resource_id = os.getenv("VOLCENGINE_TTS_RESOURCE_ID", "seed-tts-2.0")
session_id = str(uuid.uuid4())

# Event types (from official docs)
class Event(IntEnum):
    NONE = 0
    START_CONNECTION = 1
    FINISH_CONNECTION = 2
    CONNECTION_STARTED = 50
    CONNECTION_FAILED = 51
    CONNECTION_FINISHED = 52
    START_SESSION = 100
    FINISH_SESSION = 102
    SESSION_STARTED = 150
    SESSION_FINISHED = 152
    SESSION_FAILED = 153
    TASK_REQUEST = 200
    TTS_SENTENCE_START = 350
    TTS_SENTENCE_END = 351
    TTS_RESPONSE = 352


def build_start_connection_frame() -> bytes:
    """Build StartConnection frame (no session_id, no payload) - exactly as CSDN demo"""
    frame = bytearray()
    
    # Header (4 bytes) - EXACT format from CSDN blog
    frame.append(0b0001_0001)  # version=1, header_size=1 (4 bytes)
    frame.append(0b0001_0100)  # has_event_type=1, serialization=0 (NO serialization for event_type field)
    frame.append(0b0001_0000)  # flags=0, compression=0  
    frame.append(0b0000_0000)  # reserved
    
    # Event Type: START_CONNECTION (4 bytes, big-endian int32)
    frame.extend(struct.pack(">i", Event.START_CONNECTION))
    
    # Empty payload
    payload = json.dumps({}).encode()
    payload_len = struct.pack(">I", len(payload))
    
    return bytes(frame + payload_len + payload)


def build_frame(event_type: int, payload: dict = None, session_id: str = "") -> bytes:
    """Build binary frame with session_id and optional payload"""
    frame = bytearray()
    
    # Session ID bytes
    session_id_bytes = session_id.encode('utf-8') if session_id else b""
    
    # Payload bytes
    if payload is not None:
        payload_json = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    else:
        payload_json = b"{}"
    
    # Header (4 bytes)
    frame.append(0b0001_0001)  # version=1, header_size=1
    frame.append(0b0001_0001)  # has_event_type=1, serialization=1 (JSON)
    frame.append(0b0000_0000)  # flags=0, compression=0
    frame.append(0b0000_0000)  # reserved
    
    # Event Type (4 bytes, big-endian int32)
    frame.extend(struct.pack(">i", event_type))
    
    # Session ID length (4 bytes, big-endian uint32)
    frame.extend(struct.pack(">I", len(session_id_bytes)))
    
    # Session ID
    if session_id_bytes:
        frame.extend(session_id_bytes)
    
    # Payload length (4 bytes, big-endian uint32)
    frame.extend(struct.pack(">I", len(payload_json)))
    
    # Payload data
    frame.extend(payload_json)
    
    return bytes(frame)


# Test parameters
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
error_state = {"error": None, "code": None}

def on_open(ws):
    print("\n[OPEN] WebSocket connected")
    
    # Send StartConnection frame (no session_id, no payload)
    start_conn_frame = build_start_connection_frame()
    print(f"[SEND] StartConnection frame ({len(start_conn_frame)} bytes)")
    print(f"  Hex: {start_conn_frame.hex()}")
    ws.send(start_conn_frame, opcode=websocket.ABNF.OPCODE_BINARY)

def on_message(ws, message):
    if isinstance(message, (bytes, bytearray)):
        print(f"\n[BINARY] Received {len(message)} bytes")
        if len(message) < 300:
            print(f"  Hex: {message.hex()}")
            try:
                # Parse binary frame
                if len(message) >= 16:
                    # Parse header
                    header = message[0:4]
                    event_type_bytes = message[4:8]
                    event_type = struct.unpack(">i", event_type_bytes)[0]
                    
                    print(f"  Header: {header.hex()}")
                    print(f"  Event Type: {event_type} ({Event(event_type).name if event_type in Event._value2member_map_ else 'UNKNOWN'})")
                    
                    # Parse session_id and payload
                    offset = 8  # After header + event_type
                    session_id_len = struct.unpack(">I", message[offset:offset+4])[0]
                    offset += 4
                    
                    session_id_received = ""
                    if session_id_len > 0:
                        session_id_received = message[offset:offset+session_id_len].decode('utf-8')
                        offset += session_id_len
                        print(f"  Session ID: {session_id_received}")
                    
                    payload_len = struct.unpack(">I", message[offset:offset+4])[0]
                    offset += 4
                    
                    payload_data = b""
                    if payload_len > 0:
                        payload_data = message[offset:offset+payload_len]
                        payload_text = payload_data.decode('utf-8', errors='replace')
                        print(f"  Payload: {payload_text[:200]}")
                    
                    # Handle different events
                    if event_type == Event.CONNECTION_STARTED:
                        print(f"\n[SUCCESS!] Connection established!")
                        
                        # Send StartSession frame
                        start_session_payload = {
                            "req_params": req_params,
                        }
                        start_session_frame = build_frame(
                            Event.START_SESSION,
                            payload=start_session_payload,
                            session_id=session_id
                        )
                        print(f"\n[SEND] StartSession frame ({len(start_session_frame)} bytes)")
                        ws.send(start_session_frame, opcode=websocket.ABNF.OPCODE_BINARY)
                        return
                    
                    if event_type == Event.SESSION_STARTED:
                        # Send TaskRequest frame
                        task_request_frame = build_frame(
                            Event.TASK_REQUEST,
                            payload={"text": text},
                            session_id=session_id
                        )
                        print(f"\n[SEND] TaskRequest frame ({len(task_request_frame)} bytes)")
                        ws.send(task_request_frame, opcode=websocket.ABNF.OPCODE_BINARY)
                        return
                    
                    if event_type == Event.SESSION_FINISHED:
                        # Send FinishSession frame
                        finish_session_frame = build_frame(
                            Event.FINISH_SESSION,
                            session_id=session_id
                        )
                        print(f"\n[SEND] FinishSession frame")
                        ws.send(finish_session_frame, opcode=websocket.ABNF.OPCODE_BINARY)
                        return
                    
                    if event_type == Event.CONNECTION_FINISHED:
                        print(f"\n[CLOSE] Connection finished")
                        ws.close()
                        return
                    
                    if event_type in (Event.SESSION_FAILED, Event.CONNECTION_FAILED):
                        error_state["error"] = payload_text.decode('utf-8', errors='replace') if payload_data else "Unknown"
                        print(f"\n[ERROR] {error_state['error']}")
                        ws.close()
                        return
                    
                    if event_type == Event.TTS_RESPONSE:
                        # This is audio data
                        print(f"  [AUDIO] Received TTS response audio chunk")
                        audio_chunks.append(payload_data)
                        return
                        
            except Exception as e:
                print(f"  Parse error: {e}")
                import traceback
                traceback.print_exc()
        
        audio_chunks.append(bytes(message))
        return
    
    try:
        payload = json.loads(message)
        events.append(payload)
        event_type_str = payload.get("event_type") or payload.get("EventType")
        print(f"\n[RECV] Event: {event_type_str}")
        print(f"  Payload: {json.dumps(payload, ensure_ascii=False, indent=2)[:500]}")
        
        if event_type_str == "ConnectionStarted":
            print(f"\n[SUCCESS!] Connection established!")
            
            # Send StartSession frame
            start_session_payload = {
                "req_params": req_params,
            }
            start_session_frame = build_frame(
                Event.START_SESSION,
                payload=start_session_payload,
                session_id=session_id
            )
            print(f"\n[SEND] StartSession frame ({len(start_session_frame)} bytes)")
            ws.send(start_session_frame, opcode=websocket.ABNF.OPCODE_BINARY)
            return
        
        if event_type_str == "SessionStarted":
            # Send TaskRequest frame
            task_request_frame = build_frame(
                Event.TASK_REQUEST,
                payload={"text": text},
                session_id=session_id
            )
            print(f"\n[SEND] TaskRequest frame ({len(task_request_frame)} bytes)")
            ws.send(task_request_frame, opcode=websocket.ABNF.OPCODE_BINARY)
            return
        
        if event_type_str == "SessionFinished":
            # Send FinishSession frame
            finish_session_frame = build_frame(
                Event.FINISH_SESSION,
                session_id=session_id
            )
            print(f"\n[SEND] FinishSession frame")
            ws.send(finish_session_frame, opcode=websocket.ABNF.OPCODE_BINARY)
            return
        
        if event_type_str == "ConnectionFinished":
            print(f"\n[CLOSE] Connection finished")
            ws.close()
            return
        
        if event_type_str in ("SessionFailed", "ConnectionFailed"):
            error_msg = payload.get("payload", {}).get("message") or payload.get("message", "Unknown")
            error_state["error"] = error_msg
            error_state["code"] = payload.get("code")
            print(f"\n[ERROR] {error_state['code']}: {error_state['error']}")
            ws.close()
            return
            
    except Exception as e:
        print(f"\n[PARSE ERROR] {e}")
        print(f"  Raw message: {message[:200]}")

def on_error(ws, error):
    print(f"\n[WS ERROR] {error}")
    error_state["error"] = str(error)

def on_close(ws, close_status_code, close_msg):
    print(f"\n[CLOSE] Status: {close_status_code}, Message: {close_msg}")


# Top-level code would run on `import`, and pytest collects this file by name, so the
# live session stays behind a guard: importing it must not spend a real TTS call.
if __name__ == "__main__":
    print(f"WebSocket URL: {ws_url}")
    print(f"API Key: {'configured' if api_key else 'NOT SET'}")
    print(f"Resource ID: {resource_id}")
    print(f"Session ID: {session_id}")
    print("=" * 80)

    print("\nStarting WebSocket connection with BINARY FRAMES...")
    ws = websocket.WebSocketApp(
        ws_url,
        header={
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": resource_id,
        },
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    ws.run_forever(ping_timeout=10, ping_interval=30)

    print("\n" + "=" * 80)
    print(f"Total events received: {len(events)}")
    print(f"Total audio chunks: {len(audio_chunks)}")
    print(f"Error state: {error_state}")
