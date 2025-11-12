"""
方案2：批量处理器
支持并行执行多个子任务，提升工作流效率
"""
import asyncio
from typing import List, Dict, Any, Callable, Optional
import logging
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    批量任务处理器
    
    功能：
    1. 并行执行多个子任务
    2. 自动管理并发数量
    3. 错误处理和重试机制
    4. 进度跟踪
    """
    
    def __init__(self, max_concurrent: int = 3):
        """
        初始化批量处理器
        
        Args:
            max_concurrent: 最大并发数（默认3）
        """
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
    async def execute_parallel(
        self,
        tasks: List[Dict[str, Any]],
        executor: Callable,
        progress_callback: Optional[Callable] = None,
        retry_on_error: bool = True,
        max_retries: int = 2
    ) -> List[Dict[str, Any]]:
        """
        并行执行多个任务
        
        Args:
            tasks: 任务列表，每个任务是一个字典
            executor: 执行函数，接收单个任务，返回结果
            progress_callback: 进度回调函数(completed, total, result)
            retry_on_error: 是否在错误时重试
            max_retries: 最大重试次数
        
        Returns:
            结果列表
        """
        total = len(tasks)
        completed = 0
        results = []
        
        logger.info(f"🚀 开始批量处理: {total} 个任务，最大并发数={self.max_concurrent}")
        start_time = time.time()
        
        async def execute_with_semaphore(task: Dict[str, Any], index: int):
            """使用信号量控制并发"""
            nonlocal completed
            
            async with self.semaphore:
                retry_count = 0
                last_error = None
                
                while retry_count <= max_retries:
                    try:
                        logger.info(f"📌 执行任务 {index + 1}/{total}: {task.get('name', 'unnamed')}")
                        
                        # 执行任务
                        result = await executor(task)
                        
                        # 更新进度
                        completed += 1
                        
                        # 调用进度回调
                        if progress_callback:
                            try:
                                await progress_callback(completed, total, result)
                            except Exception as e:
                                logger.error(f"❌ 进度回调失败: {e}")
                        
                        logger.info(
                            f"✅ 任务完成 {index + 1}/{total} "
                            f"(进度: {completed}/{total}, {completed/total*100:.1f}%)"
                        )
                        
                        return {
                            "task": task,
                            "result": result,
                            "status": "success",
                            "index": index
                        }
                    
                    except Exception as e:
                        last_error = e
                        retry_count += 1
                        
                        if retry_on_error and retry_count <= max_retries:
                            logger.warning(
                                f"⚠️ 任务失败，重试 {retry_count}/{max_retries}: "
                                f"task={task.get('name')}, error={e}"
                            )
                            await asyncio.sleep(1 * retry_count)  # 指数退避
                        else:
                            logger.error(f"❌ 任务失败: {task.get('name')}, error={e}")
                            completed += 1
                            
                            return {
                                "task": task,
                                "result": None,
                                "status": "failed",
                                "error": str(e),
                                "index": index
                            }
        
        # 创建所有任务
        task_coroutines = [
            execute_with_semaphore(task, i) 
            for i, task in enumerate(tasks)
        ]
        
        # 并行执行
        results = await asyncio.gather(*task_coroutines, return_exceptions=False)
        
        # 统计
        success_count = sum(1 for r in results if r and r["status"] == "success")
        failed_count = sum(1 for r in results if r and r["status"] == "failed")
        elapsed_time = time.time() - start_time
        
        logger.info(
            f"✅ 批量处理完成: "
            f"总数={total}, 成功={success_count}, 失败={failed_count}, "
            f"耗时={elapsed_time:.2f}秒"
        )
        
        # 过滤掉 None 结果（类型安全）
        return [r for r in results if r is not None]
    
    async def execute_batch_with_dependencies(
        self,
        task_graph: Dict[str, Dict[str, Any]],
        executor: Callable,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        执行有依赖关系的批量任务（拓扑排序执行）
        
        Args:
            task_graph: 任务图，格式：
                {
                    "task_id": {
                        "data": {...},
                        "dependencies": ["parent_task_id1", "parent_task_id2"]
                    }
                }
            executor: 执行函数
            progress_callback: 进度回调
        
        Returns:
            所有任务的结果字典
        """
        logger.info(f"🌳 开始执行依赖任务图: {len(task_graph)} 个任务")
        
        # 结果存储
        results = {}
        completed_tasks = set()
        total_tasks = len(task_graph)
        
        # 找到所有无依赖的任务（根节点）
        def get_ready_tasks():
            ready = []
            for task_id, task_info in task_graph.items():
                if task_id in completed_tasks:
                    continue
                
                dependencies = task_info.get("dependencies", [])
                if all(dep in completed_tasks for dep in dependencies):
                    ready.append(task_id)
            
            return ready
        
        # 逐层执行
        while len(completed_tasks) < total_tasks:
            ready_tasks = get_ready_tasks()
            
            if not ready_tasks:
                # 检查是否有循环依赖
                remaining = set(task_graph.keys()) - completed_tasks
                if remaining:
                    logger.error(f"❌ 检测到循环依赖或无法解析的任务: {remaining}")
                    raise ValueError(f"循环依赖或无法解析的任务: {remaining}")
                break
            
            logger.info(f"📦 当前批次: {len(ready_tasks)} 个任务 - {ready_tasks}")
            
            # 并行执行当前批次
            async def execute_task(task_id: str):
                task_data = task_graph[task_id]["data"]
                
                # 传入依赖任务的结果
                dependencies = task_graph[task_id].get("dependencies", [])
                dep_results = {dep: results[dep] for dep in dependencies}
                task_data["dependency_results"] = dep_results
                
                result = await executor(task_data)
                
                return task_id, result
            
            # 执行并收集结果
            batch_results = await asyncio.gather(
                *[execute_task(tid) for tid in ready_tasks]
            )
            
            # 存储结果
            for task_id, result in batch_results:
                results[task_id] = result
                completed_tasks.add(task_id)
                
                # 进度回调
                if progress_callback:
                    try:
                        await progress_callback(
                            len(completed_tasks), 
                            total_tasks, 
                            {"task_id": task_id, "result": result}
                        )
                    except Exception as e:
                        logger.error(f"❌ 进度回调失败: {e}")
            
            logger.info(f"✅ 批次完成，进度: {len(completed_tasks)}/{total_tasks}")
        
        logger.info(f"✅ 依赖任务图执行完成: {total_tasks} 个任务")
        return results


# 全局单例
_batch_processor: Optional[BatchProcessor] = None


def get_batch_processor(max_concurrent: int = 3) -> BatchProcessor:
    """获取批量处理器单例"""
    global _batch_processor
    if _batch_processor is None:
        _batch_processor = BatchProcessor(max_concurrent=max_concurrent)
    return _batch_processor
