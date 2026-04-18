"""
TTS 智能调度系统集成测试

测试内容：
1. 验证 4 个已注册 TTS 模型是否正确注册
2. 验证 AgentSmartDispatchClient 是否正常工作
3. 验证 BaseAgent 是否正确集成调度客户端
4. 验证路由决策和降级机制
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

def test_model_registration():
    print("\n=== Test 1: Verify TTS Model Registration ===")
    
    from adapters.registry import registry as model_registry
    
    expected_models = [
        "MiniMax/speech-2.8-turbo",
        "MiniMax/speech-2.8-hd",
        "qwen3-tts-flash",
        "cosyvoice-v3-plus",
    ]
    
    for model_id in expected_models:
        adapter = model_registry.get_adapter(model_id)
        if adapter:
            spec = adapter.spec
            print(f"[OK] {model_id}: {spec.name} (latency: {spec.avg_latency_seconds}s)")
        else:
            print(f"[FAIL] {model_id}: not registered")
    
    tts_specs = model_registry.get_specs_by_modality("text_to_speech")
    print(f"\nTotal TTS models registered: {len(tts_specs)}")


def test_dispatch_client():
    print("\n=== Test 2: Verify Dispatch Client ===")
    
    try:
        from app.services.audiobook.agent_dispatch_client import client as tts_client
        
        models = tts_client.get_available_models()
        print(f"[OK] Dispatch client available, {len(models)} models registered:")
        for model in models:
            print(f"   - {model['name']} ({model['provider']}, {model['latency_seconds']}s)")
        
        print("\n[OK] Dispatch client initialized successfully")
        print(f"   Default strategy: {tts_client._default_strategy}")
        print(f"   Supported strategies: {list(tts_client.STRATEGY_MAP.keys())}")
        print(f"   Agent strategy mapping: {tts_client.AGENT_STRATEGY_DEFAULTS}")
        
    except ImportError as e:
        print(f"[FAIL] Dispatch client import failed: {e}")
    except Exception as e:
        print(f"[FAIL] Dispatch client test failed: {e}")


def test_base_agent_integration():
    print("\n=== Test 3: Verify BaseAgent Integration ===")
    
    try:
        from app.services.agents.agents import BaseAgent, ContentCreatorAgent, CharacterDesignerAgent
        
        content_agent = ContentCreatorAgent()
        print(f"[OK] ContentCreatorAgent created successfully")
        print(f"   Name: {content_agent.name}")
        print(f"   TTS dispatch client: {'[OK] loaded' if content_agent.tts_dispatch_client else '[FAIL] not loaded'}")
        
        char_agent = CharacterDesignerAgent()
        print(f"\n[OK] CharacterDesignerAgent created successfully")
        print(f"   Name: {char_agent.name}")
        print(f"   TTS dispatch client: {'[OK] loaded' if char_agent.tts_dispatch_client else '[FAIL] not loaded'}")
        
    except Exception as e:
        import traceback
        print(f"[FAIL] BaseAgent integration test failed: {e}")
        traceback.print_exc()


def test_engine_integration():
    print("\n=== Test 4: Verify AudiobookEngine Integration ===")
    
    try:
        from app.services.audiobook.engine import AudiobookEngine, TTS_DISPATCH_AVAILABLE
        
        print(f"[OK] TTS dispatch system available: {TTS_DISPATCH_AVAILABLE}")
        
        if TTS_DISPATCH_AVAILABLE:
            from app.services.audiobook.engine import tts_dispatch_client
            models = tts_dispatch_client.get_available_models()
            print(f"   Registered models: {len(models)}")
            for model in models:
                print(f"   - {model['name']}")
        
    except Exception as e:
        import traceback
        print(f"[FAIL] Engine integration test failed: {e}")
        traceback.print_exc()


def test_routing_logic():
    print("\n=== Test 5: Verify Routing Logic ===")
    
    try:
        from schemas.task_spec import TaskSpec, PriorityProfile
        from schemas.common import Priority, Modality
        from core.router import router as smart_router
        
        task = TaskSpec(
            task_id="test_tts_routing",
            prompt="This is a test text",
            modality=Modality.TEXT_TO_SPEECH,
            priority_profile=PriorityProfile(
                quality=0.40,
                cost=0.30,
                latency=0.30,
            ),
        )
        
        for strategy_name in ["quality", "speed", "balanced", "cost"]:
            try:
                result = smart_router.route_with_fallback_by_strategy(
                    task=task,
                    strategy=strategy_name,
                    max_fallbacks=2,
                )
                print(f"[OK] Strategy '{strategy_name}':")
                print(f"   Primary model: {result.selected_model.id}")
                print(f"   Fallback models: {[m.id for m in result.fallback_models]}")
                print(f"   Score: {result.score:.3f}")
            except Exception as e:
                print(f"[WARN] Strategy '{strategy_name}' routing failed: {e}")
                
    except Exception as e:
        import traceback
        print(f"[FAIL] Routing logic test failed: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    print("TTS Dispatch System Integration Test")
    print("=" * 60)
    
    test_model_registration()
    test_dispatch_client()
    test_base_agent_integration()
    test_engine_integration()
    test_routing_logic()
    
    print("\n" + "=" * 60)
    print("All tests completed")
