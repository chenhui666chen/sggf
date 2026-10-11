"""日志汇聚工具：把 uvicorn 系列 logger 的日志汇入 root handler。"""

import logging

# uvicorn 默认日志配置："uvicorn" 父 logger 持有控制台 handler 且 propagate=False，
# "uvicorn.error" 自身无 handler，靠向父级传播输出，因此永远到不了 root
UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


def attach_uvicorn_logs_to_root() -> None:
    """让 uvicorn.* 汇入 root handler（控制台 + 轮转文件）。

    必须在 uvicorn 自身的 dictConfig 之后调用（app.main 导入时机满足该顺序）：
    摘掉自带 handler 避免控制台重复输出，打开 propagate 交给 root 统一落盘。
    不改动 logger 级别，沿用 uvicorn/root 既有配置，避免覆盖日志级别设定。
    """
    for name in UVICORN_LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
