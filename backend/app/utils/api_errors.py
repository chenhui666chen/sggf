from enum import Enum
from typing import Any, Dict, Optional

from fastapi import HTTPException, status


class ErrorCode(str, Enum):
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    RUN_ALREADY_RUNNING = "RUN_ALREADY_RUNNING"
    RUN_INVALID_STATE = "RUN_INVALID_STATE"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_NO_PERMISSION = "PROJECT_NO_PERMISSION"
    CHAPTER_NOT_FOUND = "CHAPTER_NOT_FOUND"
    ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    INVALID_RUN_ID = "INVALID_RUN_ID"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_PATH = "INVALID_PATH"
    CONTRACT_INVALID = "CONTRACT_INVALID"
    SHOT_NOT_FOUND = "SHOT_NOT_FOUND"
    ROLE_NOT_IN_SCOPE = "ROLE_NOT_IN_SCOPE"
    UPLOAD_LIMIT_MISCONFIGURED = "UPLOAD_LIMIT_MISCONFIGURED"
    URI_MISSING = "URI_MISSING"
    URI_INVALID = "URI_INVALID"


ERROR_MESSAGES: Dict[ErrorCode, str] = {
    ErrorCode.RUN_NOT_FOUND: "运行记录不存在",
    ErrorCode.RUN_ALREADY_RUNNING: "任务正在执行中，无法执行该操作",
    ErrorCode.RUN_INVALID_STATE: "任务状态不正确",
    ErrorCode.PROJECT_NOT_FOUND: "项目不存在",
    ErrorCode.PROJECT_NO_PERMISSION: "无权限访问该项目",
    ErrorCode.CHAPTER_NOT_FOUND: "章节不存在",
    ErrorCode.ASSET_NOT_FOUND: "素材不存在",
    ErrorCode.INVALID_PARAMETER: "参数不合法",
    ErrorCode.INVALID_RUN_ID: "run_id 格式不合法",
    ErrorCode.FILE_TOO_LARGE: "上传文件大小超出限制",
    ErrorCode.INVALID_PATH: "路径不合法",
    ErrorCode.CONTRACT_INVALID: "契约数据无效",
    ErrorCode.SHOT_NOT_FOUND: "镜头不存在",
    ErrorCode.ROLE_NOT_IN_SCOPE: "该角色不在当前素材库生成范围内（群像角色不会生成素材）",
    ErrorCode.UPLOAD_LIMIT_MISCONFIGURED: "上传限制配置错误",
    ErrorCode.URI_MISSING: "缺少 URI 参数",
    ErrorCode.URI_INVALID: "URI 格式不合法",
}


class APIError(HTTPException):
    def __init__(
        self,
        error_code: ErrorCode,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        detail: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.error_code = error_code
        message = detail or ERROR_MESSAGES.get(error_code, "未知错误")
        self.extra = extra or {}
        super().__init__(status_code=status_code, detail=message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code.value,
            "message": self.detail,
            **self.extra,
        }


def raise_not_found(error_code: ErrorCode, detail: Optional[str] = None) -> None:
    raise APIError(error_code, status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def raise_bad_request(error_code: ErrorCode, detail: Optional[str] = None) -> None:
    raise APIError(error_code, status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def raise_forbidden(error_code: ErrorCode, detail: Optional[str] = None) -> None:
    raise APIError(error_code, status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def raise_conflict(error_code: ErrorCode, detail: Optional[str] = None) -> None:
    raise APIError(error_code, status_code=status.HTTP_409_CONFLICT, detail=detail)


def raise_unprocessable(error_code: ErrorCode, detail: Optional[str] = None) -> None:
    raise APIError(
        error_code, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
    )
