# -*- coding: utf-8 -*-
"""
Quick test for MiniMax TTS models with existing DASHSCOPE_API_KEY.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load .env
from dotenv import load_dotenv
load_dotenv()

def test_minimax_tts():
    """Test MiniMax TTS with real API call."""
    print("="*70)
    print("MiniMax TTS Real API Call Test")
    print("="*70)
    
    # Check API key
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("[FAIL] DASHSCOPE_API_KEY not found in .env")
        return False
    
    print(f"[OK] DASHSCOPE_API_KEY found: {api_key[:10]}...{api_key[-10:]}")
    
    try:
        from adapters.adapter_helpers import synthesize_speech_sync
        
        # Test MiniMax Turbo
        print("\n" + "-"*70)
        print("Test 1: MiniMax Speech 2.8 Turbo")
        print("-"*70)
        
        result = synthesize_speech_sync(
            text="这是一个测试文本，用于验证 MiniMax 语音合成功能。",
            voice_params={
                "voice_id": "female-wenrou",  # 温柔女声
                "speed": 1.0,
                "pitch": 1.0,
                "volume": 1.0,
            },
            emotion=None,
            model_id="minimax-speech-2.8-turbo",
        )
        
        if result.success:
            print(f"[OK] Generation successful!")
            print(f"     Audio data length: {len(result.data)} bytes")
            print(f"     Cost: {result.cost}")
            
            # Save to file
            import base64
            output_path = "test_minimax_turbo.mp3"
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(result.data))
            print(f"[OK] Audio saved to {output_path}")
        else:
            print(f"[FAIL] Generation failed: {result.error}")
        
        # Test MiniMax HD
        print("\n" + "-"*70)
        print("Test 2: MiniMax Speech 2.8 HD")
        print("-"*70)
        
        result = synthesize_speech_sync(
            text="这是高质量测试，使用 MiniMax HD 旗舰模型。",
            voice_params={
                "voice_id": "hd-female-qingcheng",  # 倾城女声
                "speed": 0.9,
                "pitch": 1.0,
                "volume": 0.95,
            },
            emotion=None,
            model_id="minimax-speech-2.8-hd",
        )
        
        if result.success:
            print(f"[OK] Generation successful!")
            print(f"     Audio data length: {len(result.data)} bytes")
            print(f"     Cost: {result.cost}")
            
            # Save to file
            output_path = "test_minimax_hd.mp3"
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(result.data))
            print(f"[OK] Audio saved to {output_path}")
        else:
            print(f"[FAIL] Generation failed: {result.error}")
        
        return True
    
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_model_registry():
    """Test that models are registered correctly."""
    print("\n" + "="*70)
    print("Model Registry Check")
    print("="*70)
    
    from adapters.registry import ModelRegistry
    
    registry = ModelRegistry()
    all_specs = registry.get_all_specs()
    
    minimax_models = [
        spec for spec in all_specs 
        if "minimax" in spec.id.lower()
    ]
    
    if minimax_models:
        print(f"[OK] Found {len(minimax_models)} MiniMax model(s):")
        for model in minimax_models:
            print(f"     - {model.id}")
            print(f"       Name: {model.name}")
            print(f"       Provider: {model.provider}")
            
            # Check quality metrics
            if hasattr(model.quality_metrics, 'overall_score'):
                quality = model.quality_metrics.overall_score
            else:
                quality = model.quality_metrics.get('overall_score', 'N/A') if isinstance(model.quality_metrics, dict) else 'N/A'
            print(f"       Quality: {quality}")
            
            # Check pricing info
            pricing_info = model.pricing_info if hasattr(model, 'pricing_info') else None
            if pricing_info:
                if isinstance(pricing_info, dict):
                    ref_price = pricing_info.get('reference_price', 'N/A')
                    currency = pricing_info.get('currency', '')
                    unit = pricing_info.get('unit', '')
                    source = pricing_info.get('source', 'N/A')
                    note = pricing_info.get('note', 'N/A')
                else:
                    ref_price = getattr(pricing_info, 'reference_price', 'N/A')
                    currency = getattr(pricing_info, 'currency', '')
                    unit = getattr(pricing_info, 'unit', '')
                    source = getattr(pricing_info, 'source', 'N/A')
                    note = getattr(pricing_info, 'note', 'N/A')
                
                print(f"       Pricing: {ref_price} {currency}/{unit}")
                print(f"       Source: {source}")
                print(f"       Note: {note[:50]}...")
    else:
        print("[FAIL] No MiniMax models found in registry")
        return False
    
    return True


if __name__ == "__main__":
    print("\n" + "="*70)
    print("MINIMAX TTS INTEGRATION TEST (With Existing API Key)")
    print("="*70)
    
    # Test 1: Model Registry
    registry_ok = test_model_registry()
    
    # Test 2: Real API Call (optional, requires API key)
    api_ok = test_minimax_tts()
    
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"[{'OK' if registry_ok else 'FAIL'}] Model Registry")
    print(f"[{'OK' if api_ok else 'FAIL'}] Real API Call")
    print("="*70)
    
    if registry_ok and api_ok:
        print("\n[SUCCESS] MiniMax TTS is ready to use!")
    elif registry_ok:
        print("\n[INFO] Model registry OK, but API call failed.")
        print("Check your API key and network connection.")
    else:
        print("\n[FAIL] MiniMax TTS integration incomplete.")
    
    print("="*70)
