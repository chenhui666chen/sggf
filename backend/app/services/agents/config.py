"""
配置文件 - 管理所有系统配置
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """系统配置类"""

    # DeepSeek LLM配置
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
    MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-reasoner")

    # DashScope（阿里云百炼）LLM配置（qwen-*）
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_API_BASE = os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    # Embedding模型配置（使用DeepSeek Embeddings）
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "deepseek-embedding")
    EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_API_BASE = os.getenv("EMBEDDING_API_BASE", "https://api.deepseek.com/v1")

    # 向量数据库配置
    CHROMA_PERSIST_DIRECTORY = os.getenv("CHROMA_PERSIST_DIRECTORY", "./chroma_db")

    # Agent配置
    MAX_CONTEXT_LENGTH = int(os.getenv("MAX_CONTEXT_LENGTH", "4000"))
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))

    @classmethod
    def validate(cls):
        """验证配置是否完整"""
        errors = []
        warnings = []
        
        # 检查DeepSeek API Key
        if not cls.DEEPSEEK_API_KEY:
            errors.append("❌ 未配置 DEEPSEEK_API_KEY")
            errors.append("   请在 .env 文件中设置 DEEPSEEK_API_KEY")
        elif cls.DEEPSEEK_API_KEY in {"your-api-key-here", "your-deepseek-api-key-here"}:
            warnings.append("⚠️  DEEPSEEK_API_KEY 使用默认值，请修改为实际的API Key")
        
        # 检查Embedding API Key
        if not cls.EMBEDDING_API_KEY:
            if cls.DASHSCOPE_API_KEY:
                warnings.append("⚠️  未配置 EMBEDDING_API_KEY，将使用 DASHSCOPE_API_KEY")
            elif cls.DEEPSEEK_API_KEY:
                warnings.append("⚠️  未配置 EMBEDDING_API_KEY，将使用 DEEPSEEK_API_KEY")

        # 检查DashScope API Key（qwen-* 模型）
        if not cls.DASHSCOPE_API_KEY:
            errors.append("❌ 未配置 DASHSCOPE_API_KEY")
            errors.append("   请在 .env 文件中设置 DASHSCOPE_API_KEY")
        elif cls.DASHSCOPE_API_KEY in {"your-api-key-here", "your-dashscope-api-key-here"}:
            warnings.append("⚠️  DASHSCOPE_API_KEY 使用默认值，请修改为实际的API Key")
        
        # 输出结果
        if errors or warnings:
            print("\n" + "="*60)
            print("📋 配置检查结果")
            print("="*60)
            
            if warnings:
                print("\n⚠️  警告：")
                for warning in warnings:
                    print(f"  {warning}")
            
            if errors:
                print("\n❌ 错误：")
                for error in errors:
                    print(f"  {error}")
                print("\n💡 解决方法：")
                print("  1. 复制 .env.example 为 .env")
                print("  2. 编辑 .env 文件，填入正确的配置")
                print("  3. 重启应用")
                print("="*60 + "\n")
                raise ValueError("配置验证失败")
            else:
                print("\n✅ 配置检查通过（有警告但不影响运行）")
                print("="*60 + "\n")
        else:
            print("✅ 配置验证通过")
        
        return True
