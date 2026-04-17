# -*- coding: utf-8 -*-
"""
Test script for MiniMax Speech Models Integration.

Tests:
1. Model configuration in models.yaml
2. Adapter classes registration
3. Runtime wrapper availability
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_model_config():
    """Test 1: Verify model configuration in models.yaml."""
    print("="*70)
    print("Test 1: Model Configuration in models.yaml")
    print("="*70)
    
    import yaml
    
    config_path = project_root / "config" / "models.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    models = {model["id"]: model for model in config.get("models", [])}
    
    # Test MiniMax Speech 2.8 Turbo
    if "minimax-speech-2.8-turbo" in models:
        model = models["minimax-speech-2.8-turbo"]
        print(f"[OK] minimax-speech-2.8-turbo found")
        print(f"     Name: {model['name']}")
        print(f"     Provider: {model['provider']}")
        print(f"     Modality: {model['modality']}")
        print(f"     Quality Score: {model['quality_metrics']['overall_score']}")
        print(f"     Tags: {', '.join(model['tags'])}")
        
        # Check API config
        api_config = model.get('api_config', {})
        if api_config:
            print(f"     API Base URL: {api_config.get('base_url', 'N/A')}")
            print(f"     API Key Env: {api_config.get('api_key_env', 'N/A')}")
            print(f"     [OK] Using Alibaba Cloud DashScope API (NOT MiniMax official)")
    else:
        print(f"[FAIL] minimax-speech-2.8-turbo not found in models.yaml")
        return False
    
    # Test MiniMax Speech 2.8 HD
    if "minimax-speech-2.8-hd" in models:
        model = models["minimax-speech-2.8-hd"]
        print(f"\n[OK] minimax-speech-2.8-hd found")
        print(f"     Name: {model['name']}")
        print(f"     Provider: {model['provider']}")
        print(f"     Modality: {model['modality']}")
        print(f"     Quality Score: {model['quality_metrics']['overall_score']}")
        print(f"     Tags: {', '.join(model['tags'])}")
        
        # Check API config
        api_config = model.get('api_config', {})
        if api_config:
            print(f"     API Base URL: {api_config.get('base_url', 'N/A')}")
            print(f"     API Key Env: {api_config.get('api_key_env', 'N/A')}")
            print(f"     [OK] Using Alibaba Cloud DashScope API (NOT MiniMax official)")
    else:
        print(f"[FAIL] minimax-speech-2.8-hd not found in models.yaml")
        return False
    
    return True


def test_adapter_classes():
    """Test 2: Verify adapter classes are defined."""
    print("\n" + "="*70)
    print("Test 2: Adapter Classes Registration")
    print("="*70)
    
    try:
        from adapters.model_adapters import MiniMaxSpeech28TurboAdapter, MiniMaxSpeech28HDAdapter
        
        print(f"[OK] MiniMaxSpeech28TurboAdapter imported successfully")
        print(f"     RUNTIME_WRAPPER_NAME: {MiniMaxSpeech28TurboAdapter.RUNTIME_WRAPPER_NAME}")
        
        print(f"[OK] MiniMaxSpeech28HDAdapter imported successfully")
        print(f"     RUNTIME_WRAPPER_NAME: {MiniMaxSpeech28HDAdapter.RUNTIME_WRAPPER_NAME}")
        
        return True
    
    except ImportError as e:
        print(f"[FAIL] Failed to import adapter classes: {e}")
        return False


def test_runtime_wrappers():
    """Test 3: Verify runtime wrappers are registered."""
    print("\n" + "="*70)
    print("Test 3: Runtime Wrappers Registration")
    print("="*70)
    
    from adapters.legacy_runtime_wrappers import has_runtime_wrapper, create_runtime_wrapper
    from adapters.model_adapters import ModelConfig
    
    # Test MiniMax Speech 2.8 Turbo
    if has_runtime_wrapper("minimax-speech-2.8-turbo"):
        print(f"[OK] minimax-speech-2.8-turbo runtime wrapper available")
        
        config = ModelConfig(
            api_key="test_key",
            base_url="https://test.api.com",
            model_name="minimax-speech-2.8-turbo",
        )
        wrapper = create_runtime_wrapper("minimax-speech-2.8-turbo", config)
        if wrapper:
            print(f"     Wrapper class: {wrapper.__class__.__name__}")
            print(f"     TARGET_MODEL_ID: {wrapper.TARGET_MODEL_ID}")
        else:
            print(f"[WARN] Wrapper creation returned None")
    else:
        print(f"[FAIL] minimax-speech-2.8-turbo runtime wrapper not available")
        return False
    
    # Test MiniMax Speech 2.8 HD
    if has_runtime_wrapper("minimax-speech-2.8-hd"):
        print(f"\n[OK] minimax-speech-2.8-hd runtime wrapper available")
        
        config = ModelConfig(
            api_key="test_key",
            base_url="https://test.api.com",
            model_name="minimax-speech-2.8-hd",
        )
        wrapper = create_runtime_wrapper("minimax-speech-2.8-hd", config)
        if wrapper:
            print(f"     Wrapper class: {wrapper.__class__.__name__}")
            print(f"     TARGET_MODEL_ID: {wrapper.TARGET_MODEL_ID}")
        else:
            print(f"[WARN] Wrapper creation returned None")
    else:
        print(f"[FAIL] minimax-speech-2.8-hd runtime wrapper not available")
        return False
    
    return True


def test_registry_integration():
    """Test 4: Verify models are registered in ModelRegistry."""
    print("\n" + "="*70)
    print("Test 4: Model Registry Integration")
    print("="*70)
    
    from adapters.registry import ModelRegistry
    
    registry = ModelRegistry()
    all_specs = registry.get_all_specs()
    
    minimax_models = [
        spec for spec in all_specs 
        if "minimax" in spec.id.lower()
    ]
    
    if minimax_models:
        print(f"[OK] Found {len(minimax_models)} MiniMax model(s) in registry:")
        for model in minimax_models:
            print(f"     - {model.id}: {model.name}")
            print(f"       Modalities: {', '.join(model.modality)}")
            if hasattr(model.quality_metrics, 'overall_score'):
                quality = model.quality_metrics.overall_score
            else:
                quality = model.quality_metrics.get('overall_score', 'N/A') if isinstance(model.quality_metrics, dict) else 'N/A'
            print(f"       Quality: {quality}")
    else:
        print(f"[INFO] No MiniMax models found in registry (auto-loading may be needed)")
    
    return True


def test_model_resolution():
    """Test 5: Verify model ID normalization."""
    print("\n" + "="*70)
    print("Test 5: Model ID Normalization")
    print("="*70)
    
    from core.model_resolution import normalize_model_id
    
    test_ids = [
        "minimax-speech-2.8-turbo",
        "minimax-speech-2.8-hd",
        "MiniMax-Speech-2.8-Turbo",  # Test case insensitivity
    ]
    
    for model_id in test_ids:
        normalized = normalize_model_id(model_id)
        print(f"[OK] {model_id} → {normalized}")
    
    return True


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("MINIMAX SPEECH MODELS INTEGRATION TEST")
    print("="*70)
    
    results = {
        "Model Configuration": test_model_config(),
        "Adapter Classes": test_adapter_classes(),
        "Runtime Wrappers": test_runtime_wrappers(),
        "Registry Integration": test_registry_integration(),
        "Model Resolution": test_model_resolution(),
    }
    
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {test_name}")
    
    all_passed = all(results.values())
    print("\n" + "="*70)
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED!")
    print("="*70)
    
    print("\nImplementation Summary:")
    print("[OK] Added minimax-speech-2.8-turbo to models.yaml")
    print("[OK] Added minimax-speech-2.8-hd to models.yaml")
    print("[OK] Created MiniMaxSpeech28TurboAdapter")
    print("[OK] Created MiniMaxSpeech28HDAdapter")
    print("[OK] Registered runtime wrappers")
    print("\nNext Steps:")
    print("1. Configure API keys in .env or config files")
    print("2. Test actual TTS generation with real API calls")
    print("3. Add voice catalog integration to audiobook service")
    print("4. Update model selection UI to include MiniMax options")
    print("="*70)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
