"""
方案3：智能缓存系统
多层缓存架构，支持内存缓存、Redis缓存和知识库缓存
"""
import asyncio
import hashlib
import json
from typing import Any, Optional, Callable, Dict
from datetime import datetime, timedelta
import logging

from app.core.redis_client import LoopBoundRedis

logger = logging.getLogger(__name__)


class CacheLayer:
    """缓存层基类"""
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        raise NotImplementedError
    
    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """设置缓存"""
        raise NotImplementedError
    
    async def delete(self, key: str) -> bool:
        """删除缓存"""
        raise NotImplementedError
    
    async def clear(self) -> bool:
        """清空缓存"""
        raise NotImplementedError


class MemoryCache(CacheLayer):
    """内存缓存层（最快，容量小）"""
    
    def __init__(self, max_size: int = 100):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.max_size = max_size
        
    async def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            return None
        
        entry = self.cache[key]
        
        # 检查是否过期
        if entry["expires_at"] < datetime.now():
            del self.cache[key]
            return None
        
        logger.debug(f"⚡ 内存缓存命中: {key}")
        return entry["value"]
    
    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        # LRU 策略：如果缓存满了，删除最旧的
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k]["created_at"])
            del self.cache[oldest_key]
            logger.debug(f"🗑️ 内存缓存已满，删除最旧条目: {oldest_key}")
        
        self.cache[key] = {
            "value": value,
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(seconds=ttl)
        }
        logger.debug(f"💾 内存缓存已设置: {key}, TTL={ttl}秒")
        return True
    
    async def delete(self, key: str) -> bool:
        if key in self.cache:
            del self.cache[key]
            return True
        return False
    
    async def clear(self) -> bool:
        self.cache.clear()
        logger.info("🗑️ 内存缓存已清空")
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        now = datetime.now()
        active_count = sum(1 for v in self.cache.values() if v["expires_at"] >= now)
        expired_count = len(self.cache) - active_count
        
        return {
            "total": len(self.cache),
            "active": active_count,
            "expired": expired_count,
            "max_size": self.max_size
        }


class RedisCache(CacheLayer):
    """Redis 缓存层（容量大，持久化）"""
    
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or "redis://localhost:6379/0"
        self._redis = LoopBoundRedis(self.redis_url)
        self.enabled = False
        
    async def _ensure_connection(self):
        """确保 Redis 连接（按事件循环绑定，见 app/core/redis_client.py）"""
        if self.enabled:
            return
        
        try:
            await self._redis.get()
            self.enabled = True
            logger.info(f"✅ Redis 缓存已连接: {self.redis_url}")
        except Exception as e:
            logger.warning(f"⚠️ Redis 连接失败，将禁用 Redis 缓存: {e}")
            self.enabled = False
    
    async def get(self, key: str) -> Optional[Any]:
        await self._ensure_connection()
        if not self.enabled:
            return None
        
        try:
            client = await self._redis.get()
            value = await client.get(key)
            if value:
                logger.debug(f"🔴 Redis 缓存命中: {key}")
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"❌ Redis 读取失败: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        await self._ensure_connection()
        if not self.enabled:
            return False
        
        try:
            serialized = json.dumps(value, ensure_ascii=False)
            client = await self._redis.get()
            await client.setex(key, ttl, serialized)
            logger.debug(f"💾 Redis 缓存已设置: {key}, TTL={ttl}秒")
            return True
        except Exception as e:
            logger.error(f"❌ Redis 写入失败: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        await self._ensure_connection()
        if not self.enabled:
            return False
        
        try:
            client = await self._redis.get()
            await client.delete(key)
            return True
        except Exception as e:
            logger.error(f"❌ Redis 删除失败: {e}")
            return False
    
    async def clear(self) -> bool:
        await self._ensure_connection()
        if not self.enabled:
            return False
        
        try:
            client = await self._redis.get()
            await client.flushdb()
            logger.info("🗑️ Redis 缓存已清空")
            return True
        except Exception as e:
            logger.error(f"❌ Redis 清空失败: {e}")
            return False


class MultiLayerCache:
    """
    多层缓存系统
    
    L1: 内存缓存（最快）
    L2: Redis 缓存（持久化）
    """
    
    def __init__(
        self,
        enable_memory: bool = True,
        enable_redis: bool = False,
        redis_url: Optional[str] = None,
        memory_max_size: int = 100
    ):
        self.layers = []
        
        # L1: 内存缓存
        if enable_memory:
            self.memory_cache = MemoryCache(max_size=memory_max_size)
            self.layers.append(("memory", self.memory_cache))
            logger.info("✅ L1 内存缓存已启用")
        else:
            self.memory_cache = None
        
        # L2: Redis 缓存
        if enable_redis:
            self.redis_cache = RedisCache(redis_url=redis_url)
            self.layers.append(("redis", self.redis_cache))
            logger.info("✅ L2 Redis 缓存已启用")
        else:
            self.redis_cache = None
        
        logger.info(f"🎯 多层缓存系统初始化完成，共 {len(self.layers)} 层")
    
    def _generate_key(self, namespace: str, identifier: str) -> str:
        """生成缓存键"""
        # 使用 MD5 哈希，避免键过长
        hash_id = hashlib.md5(identifier.encode()).hexdigest()
        return f"{namespace}:{hash_id}"
    
    async def get(self, namespace: str, identifier: str) -> Optional[Any]:
        """
        从缓存获取数据（多层查询）
        
        Args:
            namespace: 命名空间（如 "llm_response", "kb_search"）
            identifier: 标识符（如查询文本、任务ID）
        
        Returns:
            缓存的值，如果未命中返回 None
        """
        key = self._generate_key(namespace, identifier)
        
        # 逐层查询
        for layer_name, layer in self.layers:
            value = await layer.get(key)
            if value is not None:
                logger.info(f"✅ 缓存命中: layer={layer_name}, namespace={namespace}")
                
                # 回填到更快的层
                await self._backfill(key, value, layer_name)
                
                return value
        
        logger.debug(f"❌ 缓存未命中: namespace={namespace}")
        return None
    
    async def set(
        self, 
        namespace: str, 
        identifier: str, 
        value: Any, 
        ttl: int = 300
    ) -> bool:
        """
        设置缓存（写入所有层）
        
        Args:
            namespace: 命名空间
            identifier: 标识符
            value: 缓存值
            ttl: 过期时间（秒）
        
        Returns:
            是否成功
        """
        key = self._generate_key(namespace, identifier)
        
        success = True
        for layer_name, layer in self.layers:
            result = await layer.set(key, value, ttl)
            if not result:
                logger.warning(f"⚠️ 缓存写入失败: layer={layer_name}")
                success = False
        
        if success:
            logger.info(f"💾 缓存已设置: namespace={namespace}, TTL={ttl}秒")
        
        return success
    
    async def _backfill(self, key: str, value: Any, from_layer: str):
        """回填缓存到更快的层"""
        for layer_name, layer in self.layers:
            if layer_name == from_layer:
                break
            
            await layer.set(key, value, ttl=300)
            logger.debug(f"🔄 缓存回填: {layer_name}")
    
    async def delete(self, namespace: str, identifier: str) -> bool:
        """删除缓存（所有层）"""
        key = self._generate_key(namespace, identifier)
        
        for _, layer in self.layers:
            await layer.delete(key)
        
        logger.info(f"🗑️ 缓存已删除: namespace={namespace}")
        return True
    
    async def clear_namespace(self, namespace: str):
        """清空指定命名空间（暂不实现，需要遍历）"""
        logger.warning("⚠️ 清空命名空间功能暂未实现")
    
    async def clear_all(self):
        """清空所有缓存"""
        for layer_name, layer in self.layers:
            await layer.clear()
            logger.info(f"🗑️ {layer_name} 缓存已清空")
    
    async def get_with_fallback(
        self,
        namespace: str,
        identifier: str,
        fallback: Callable,
        ttl: int = 300
    ) -> Any:
        """
        获取缓存，如果未命中则执行 fallback 函数并缓存结果
        
        Args:
            namespace: 命名空间
            identifier: 标识符
            fallback: 未命中时执行的函数
            ttl: 缓存过期时间
        
        Returns:
            缓存值或 fallback 结果
        """
        # 尝试从缓存获取
        cached = await self.get(namespace, identifier)
        if cached is not None:
            return cached
        
        # 执行 fallback
        logger.info(f"🔄 执行 fallback: namespace={namespace}")
        result = await fallback() if asyncio.iscoroutinefunction(fallback) else fallback()
        
        # 缓存结果
        await self.set(namespace, identifier, result, ttl)
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        stats = {}
        
        if self.memory_cache:
            stats["memory"] = self.memory_cache.get_stats()
        
        return stats


# 全局单例
_cache_system: Optional[MultiLayerCache] = None


def get_cache_system(
    enable_memory: bool = True,
    enable_redis: bool = False,
    redis_url: Optional[str] = None
) -> MultiLayerCache:
    """获取缓存系统单例"""
    global _cache_system
    if _cache_system is None:
        _cache_system = MultiLayerCache(
            enable_memory=enable_memory,
            enable_redis=enable_redis,
            redis_url=redis_url
        )
    return _cache_system

