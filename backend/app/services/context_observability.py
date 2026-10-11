# -*- coding: utf-8 -*-
"""长篇上下文观测：只记录"传了多少、裁了多少、是否调用 LLM、读了多少、剩多少预算"。

阶段 A 定位为纯观测，本模块不改变任何业务行为：不拦截请求、不修改 prompt。
观测快照同时输出结构化日志，并在内存中按项目保留最近若干条，供只读 API 与
前端上下文健康面板消费。长期持久化不在阶段 A 范围内。
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 与 workflow/helpers.py 的 _estimate_tokens_by_chars 保持同一口径（中文 1.3 倍字符）。
# 在此独立定义以避免 service 层反向依赖 api 层；阶段 C 统一预算时再收敛到唯一位置。
TOKEN_CHARS_RATIO = 1.3


def estimate_tokens(text: str) -> int:
    """按字符比例估算 token 数。"""
    return int(len(text or "") * TOKEN_CHARS_RATIO)


@dataclass
class SectionStat:
    """单个 prompt section 的观测统计。"""

    section_id: str
    source_field: str = ""
    layer: str = ""
    raw_chars: int = 0
    raw_tokens: int = 0
    final_chars: int = 0
    final_tokens: int = 0
    trim_method: str = "none"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ContextObservation:
    """一次规划/正文请求的完整上下文快照。"""

    project_id: int
    chapter_number: int
    # 请求类型：plan / plan_retry / content / content_retry / segment / regeneration /
    #           iteration_plan / revision / review / fallback / expansion / final_validation
    request_kind: str
    model_id: str = ""
    model_context_limit: int = 0
    safe_input_budget: int = 0
    sections: List[Dict[str, Any]] = field(default_factory=list)
    total_input_tokens: int = 0
    remaining_budget: int = 0
    # 上下文载荷字节数：估算的叙事上下文文本，不含固定系统规则/输出契约与控制参数，
    # 不等同完整 LLM 请求；完整请求规模以 prompt_request_bytes 为准
    context_payload_bytes: int = 0
    # 完整请求字节数：最终发送给模型的 system+user prompt 的 UTF-8 字节，权威请求规模口径
    prompt_request_bytes: int = 0
    db_rows_read: int = 0
    db_columns_read: int = 0
    rag_hits: int = 0
    rag_summary_cache_hits: int = 0
    # 本请求是否执行了缓存查询（区分"命中为零"与"未执行查询"）
    cache_lookup_performed: bool = False
    # 缓存查询三态：queried（确实查询）/ not_eligible（首章或无符合条件章节）/ unavailable（摘要器不可用）
    cache_lookup_status: str = ""
    online_llm_calls: int = 0
    # 逻辑生成步骤数/计划轮数：无法统计真实 LLM 调用时（如扩写多调用链路）用此字段，不冒充调用次数
    logical_step_count: int = 0
    # 请求最终状态：ok（正常完成）/ failed（失败路径也落库，供诊断最需要观测的失败请求）
    request_status: str = "ok"
    # 失败时的异常类型名（仅 request_status=failed 有意义）
    error_type: str = ""
    # 输出验收状态（与 request_status 解耦）：not_checked（未做输出校验）/
    # accepted（输出被采用）/ rejected（LLM 调用成功但输出被拒，如空/占位模板/重复/过短）。
    # 区分“调用成功”与“结果可接受”，避免无效输出被记成 ok 而掩盖熔断。
    output_status: str = "not_checked"
    # 输出被拒原因（仅 output_status=rejected 有意义）：
    # EmptyOutput/PlaceholderOutput/RepeatedOutput/EmptyOrShortOutput/TruncatedOutput
    output_reject_reason: str = ""
    # 截断/重生成重试语义：是否尝试过重试
    retry_attempted: bool = False
    # 重试结果：not_needed（无需重试）/ succeeded（重试产出被采用）/ failed（重试失败或仍不达标）
    retry_status: str = "not_needed"
    # 结果未被采用、回退到上一版输出（如重生成产出过短保留旧分段稿、截断重试失败保留原改稿）
    fallback_to_previous_output: bool = False
    durations_ms: Dict[str, float] = field(default_factory=dict)
    # 冲突结果（写前闸门/对齐闸门）：状态 + blocking/warning 计数
    conflict_status: str = ""
    blocking_conflict_count: int = 0
    warning_conflict_count: int = 0
    # 细纲与卷覆盖健康状态（结构化元数据，不计入 prompt token）
    outline_status: str = ""
    volume_matched: bool = False
    # 关联 ID：同一项目并发规划/正文/扩写时，用于确认快照归属
    task_id: str = ""
    request_id: str = ""
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ObservationCollector:
    """按项目保存最近观测快照的进程内单例收集器。"""

    _instance: Optional["ObservationCollector"] = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "ObservationCollector":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_per_project: int = 200) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._max_per_project = max_per_project
        self._observations: Dict[int, List[ContextObservation]] = {}
        self._lock = threading.Lock()

    def record(self, obs: ContextObservation) -> ContextObservation:
        """落盘一条结构化日志，并按项目保留最近快照。"""
        logger.info(
            "[context-observation] %s",
            json.dumps(obs.to_dict(), ensure_ascii=False, default=str),
        )
        with self._lock:
            bucket = self._observations.setdefault(obs.project_id, [])
            bucket.append(obs)
            if len(bucket) > self._max_per_project:
                self._observations[obs.project_id] = bucket[-self._max_per_project :]
        return obs

    def list_for_project(
        self,
        project_id: int,
        *,
        limit: int = 20,
        chapter_number: Optional[int] = None,
        request_kind: Optional[str] = None,
    ) -> List[ContextObservation]:
        with self._lock:
            bucket = list(self._observations.get(project_id, []))
        if chapter_number is not None:
            bucket = [o for o in bucket if o.chapter_number == chapter_number]
        if request_kind:
            bucket = [o for o in bucket if o.request_kind == request_kind]
        # 防御性归一：limit<=0 会产生 bucket[-0:]=全部 等错误语义
        normalized_limit = max(1, min(int(limit), self._max_per_project))
        return bucket[-normalized_limit:]

    def latest_for_project(
        self,
        project_id: int,
        *,
        request_kind: Optional[str] = None,
    ) -> Optional[ContextObservation]:
        items = self.list_for_project(project_id, limit=self._max_per_project, request_kind=request_kind)
        return items[-1] if items else None


collector = ObservationCollector()


class ObservationBuilder:
    """逐步组装一次 ContextObservation 的便捷构造器。"""

    def __init__(
        self,
        project_id: Optional[int],
        chapter_number: Optional[int],
        request_kind: str,
    ) -> None:
        # 观测仅供诊断、按项目分桶；独立扩写等无项目上下文的调用落 0 桶，不能因缺 project_id 打断主链路
        self.observation = ContextObservation(
            project_id=int(project_id or 0),
            chapter_number=int(chapter_number or 0),
            request_kind=request_kind,
        )
        self._timers: Dict[str, float] = {}

    def set_model(
        self,
        model_id: str,
        *,
        context_limit: int = 0,
        safe_input_budget: int = 0,
    ) -> "ObservationBuilder":
        self.observation.model_id = model_id or ""
        self.observation.model_context_limit = int(context_limit or 0)
        self.observation.safe_input_budget = int(safe_input_budget or 0)
        return self

    def add_section(
        self,
        section_id: str,
        raw_text: str,
        *,
        source_field: str = "",
        layer: str = "",
        final_text: Optional[str] = None,
        trim_method: str = "none",
    ) -> "ObservationBuilder":
        """登记一个 section：raw 为裁剪前内容，final 为最终入 prompt 内容。"""
        final = raw_text if final_text is None else final_text
        stat = SectionStat(
            section_id=section_id,
            source_field=source_field,
            layer=layer,
            raw_chars=len(raw_text or ""),
            raw_tokens=estimate_tokens(raw_text or ""),
            final_chars=len(final or ""),
            final_tokens=estimate_tokens(final or ""),
            trim_method=trim_method,
        )
        self.observation.sections.append(stat.to_dict())
        return self

    def add_section_stat(self, stat: SectionStat) -> "ObservationBuilder":
        self.observation.sections.append(stat.to_dict())
        return self

    def set_context_payload(self, payload: Any) -> "ObservationBuilder":
        """记录估算的上下文载荷序列化字节数（叙事内容，不含固定系统规则/输出契约，≠完整请求）。"""
        try:
            encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.observation.context_payload_bytes = len(encoded)
        except (TypeError, ValueError):
            # 不可 JSON 序列化的载荷不阻断观测
            self.observation.context_payload_bytes = -1
        return self

    def set_db_read(self, *, rows: int, columns: int) -> "ObservationBuilder":
        self.observation.db_rows_read = int(rows)
        self.observation.db_columns_read = int(columns)
        return self

    def set_rag(
        self,
        *,
        hits: int = 0,
        summary_cache_hits: int = 0,
        cache_lookup_performed: bool = True,
        cache_lookup_status: str = "",
    ) -> "ObservationBuilder":
        self.observation.rag_hits = int(hits)
        self.observation.rag_summary_cache_hits = int(summary_cache_hits)
        self.observation.cache_lookup_performed = bool(cache_lookup_performed)
        # 未显式给三态时从 performed 布尔回退推导，保证旧调用方仍有确定语义
        if cache_lookup_status:
            self.observation.cache_lookup_status = str(cache_lookup_status)
        else:
            self.observation.cache_lookup_status = (
                "queried" if cache_lookup_performed else "not_eligible"
            )
        return self

    def set_prompt_request_bytes(
        self,
        *,
        system_prompt: str = "",
        user_prompt: str = "",
    ) -> "ObservationBuilder":
        """记录最终发送给模型的完整请求字节数（system+user，UTF-8）。"""
        combined = f"{system_prompt or ''}{user_prompt or ''}"
        self.observation.prompt_request_bytes = len(combined.encode("utf-8"))
        return self

    def set_conflict_result(
        self,
        *,
        status: str,
        blocking_count: int = 0,
        warning_count: int = 0,
    ) -> "ObservationBuilder":
        """写入冲突结果（写前闸门/对齐闸门状态与计数）。"""
        self.observation.conflict_status = str(status or "")
        self.observation.blocking_conflict_count = int(blocking_count)
        self.observation.warning_conflict_count = int(warning_count)
        return self

    def set_online_llm_calls(self, calls: int) -> "ObservationBuilder":
        self.observation.online_llm_calls = int(calls)
        return self

    def set_logical_step_count(self, steps: int) -> "ObservationBuilder":
        """记录逻辑生成步骤数/计划轮数（非真实 LLM 调用次数）。"""
        self.observation.logical_step_count = int(steps)
        return self

    def set_request_status(
        self,
        status: str,
        *,
        error_type: str = "",
    ) -> "ObservationBuilder":
        """记录请求最终状态（ok/failed）与失败异常类型，用于失败路径兜底观测。"""
        self.observation.request_status = str(status or "ok")
        self.observation.error_type = str(error_type or "")
        return self

    def set_output_status(
        self,
        status: str,
        *,
        reject_reason: str = "",
    ) -> "ObservationBuilder":
        """记录输出验收状态（accepted/rejected/not_checked），与 request_status 解耦。

        rejected 表示 LLM 调用本身成功、但产出被有效性校验拒绝（空/占位模板/重复/过短），
        reject_reason 写具体原因，避免面板把无效输出误报为成功。
        """
        self.observation.output_status = str(status or "not_checked")
        self.observation.output_reject_reason = str(reject_reason or "")
        return self

    def set_retry(
        self,
        *,
        attempted: bool,
        status: str,
        fallback_to_previous: bool = False,
    ) -> "ObservationBuilder":
        """记录截断/重生成重试语义：是否重试、重试结果、是否回退到上一版输出。"""
        self.observation.retry_attempted = bool(attempted)
        self.observation.retry_status = str(status or "not_needed")
        self.observation.fallback_to_previous_output = bool(fallback_to_previous)
        return self

    def set_correlation(
        self,
        *,
        task_id: str = "",
        request_id: str = "",
    ) -> "ObservationBuilder":
        """写入任务/请求关联 ID，便于并发场景定位快照归属。"""
        if task_id:
            self.observation.task_id = str(task_id)
        if request_id:
            self.observation.request_id = str(request_id)
        return self

    def set_outline_health(
        self,
        *,
        outline_status: str,
        volume_matched: bool,
    ) -> "ObservationBuilder":
        """写入细纲状态与卷覆盖命中（结构化字段，不进 section 统计）。"""
        self.observation.outline_status = str(outline_status or "")
        self.observation.volume_matched = bool(volume_matched)
        return self

    @contextlib.contextmanager
    def timer(self, name: str) -> Iterator[None]:
        """计时上下文管理器，毫秒写入 durations_ms。"""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observation.durations_ms[name] = round(
                (time.perf_counter() - start) * 1000, 2
            )

    def finish(self, *, record: bool = True) -> ContextObservation:
        """汇总总 token 与剩余预算并（可选）交给收集器。"""
        total = sum(int(s.get("final_tokens") or 0) for s in self.observation.sections)
        self.observation.total_input_tokens = total
        if self.observation.safe_input_budget > 0:
            self.observation.remaining_budget = self.observation.safe_input_budget - total
        self.observation.created_at = utc_now().isoformat()
        if record:
            collector.record(self.observation)
        return self.observation
