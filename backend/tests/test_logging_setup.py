"""日志汇聚配置测试：uvicorn.* 日志必须汇入 root（控制台 + 文件）。

背景：章节生成链路里大量关键观测点用 logging.getLogger("uvicorn.error") 打印，
而 uvicorn 默认给 uvicorn/uvicorn.error/uvicorn.access 挂了自带 handler 且
propagate=False，导致这些日志只上控制台、永不落盘，线上无法回溯。
"""

import io
import logging

from app.core.logging_setup import UVICORN_LOGGER_NAMES, attach_uvicorn_logs_to_root


class _RecordCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _snapshot(names):
    return {name: (list(logging.getLogger(name).handlers), logging.getLogger(name).propagate) for name in names}


def _restore(snapshot) -> None:
    for name, (handlers, propagate) in snapshot.items():
        logger = logging.getLogger(name)
        logger.handlers = handlers
        logger.propagate = propagate


def test_uvicorn_error_logs_reach_root_handlers():
    """复现 uvicorn 自带 handler + 不传播的配置，修复后日志必须被 root handler 收到。"""
    root = logging.getLogger()
    snapshot = _snapshot(UVICORN_LOGGER_NAMES)
    root_snapshot = list(root.handlers)
    root_level = root.level
    capture = _RecordCapture()
    try:
        # 生产环境 app.main 把 root 配成 INFO 并挂控制台/文件 handler，这里同口径建模
        root.setLevel(logging.INFO)
        for name in UVICORN_LOGGER_NAMES:
            logger = logging.getLogger(name)
            logger.handlers = [logging.StreamHandler(io.StringIO())]
            logger.propagate = False
        root.addHandler(capture)

        attach_uvicorn_logs_to_root()
        logging.getLogger("uvicorn.error").info("生成档位校验通过")

        assert "生成档位校验通过" in capture.messages
    finally:
        root.handlers = root_snapshot
        root.setLevel(root_level)
        _restore(snapshot)


def test_uvicorn_logger_own_handlers_removed_to_avoid_double_output():
    """汇入 root 后必须摘掉自带 handler，否则控制台重复输出。"""
    root = logging.getLogger()
    snapshot = _snapshot(UVICORN_LOGGER_NAMES)
    root_snapshot = list(root.handlers)
    try:
        for name in UVICORN_LOGGER_NAMES:
            logger = logging.getLogger(name)
            logger.handlers = [logging.StreamHandler(io.StringIO())]
            logger.propagate = False

        attach_uvicorn_logs_to_root()

        for name in UVICORN_LOGGER_NAMES:
            logger = logging.getLogger(name)
            assert logger.handlers == []
            assert logger.propagate is True
    finally:
        root.handlers = root_snapshot
        _restore(snapshot)
