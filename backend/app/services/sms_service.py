"""
阿里云短信发送服务（手机号验证码：注册申诉/绑定/找回密码）。

直接以 RPC 风格签名调用 dysmsapi OpenAPI（httpx，不引入 SDK 依赖）；
签名/模板/AccessKey 全部配置化，测试模板与正式模板切换零代码改动。
与 EmailService 同语义：未配置抛 SmsServiceNotConfiguredError，
发送失败抛 SmsDeliveryError（由路由翻译为 503 并回滚已生成的验证码）。
"""
import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import timezone
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


class SmsServiceNotConfiguredError(RuntimeError):
    """短信服务未配置。"""


class SmsDeliveryError(RuntimeError):
    """短信发送失败。"""


def _percent_encode(value: str) -> str:
    """阿里云 RPC 签名要求的 RFC3986 编码（空格→%20，*→%2A，~ 不编码）。"""
    return quote(str(value), safe="~").replace("+", "%20").replace("*", "%2A")


class SmsService:
    """基于阿里云 SendSms OpenAPI 的短信发送服务。"""

    def is_configured(self) -> bool:
        return (
            bool(str(settings.SMS_ACCESS_KEY_ID).strip())
            and bool(str(settings.SMS_ACCESS_KEY_SECRET).strip())
            and bool(str(settings.SMS_SIGN_NAME).strip())
            and bool(str(settings.SMS_TEMPLATE_CODE).strip())
        )

    async def send_verification_code(self, phone: str, code: str) -> None:
        """发送验证码短信（模板变量固定为 ${code}）。"""
        if not self.is_configured():
            raise SmsServiceNotConfiguredError("短信服务未配置")

        params = {
            "AccessKeyId": str(settings.SMS_ACCESS_KEY_ID).strip(),
            "Action": "SendSms",
            "Format": "JSON",
            "PhoneNumbers": phone,
            "RegionId": "cn-hangzhou",
            "SignName": str(settings.SMS_SIGN_NAME).strip(),
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "TemplateCode": str(settings.SMS_TEMPLATE_CODE).strip(),
            "TemplateParam": json.dumps({"code": code}, separators=(",", ":")),
            "Timestamp": utc_now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Version": "2017-05-25",
        }
        params["Signature"] = self._sign(params)

        timeout = max(1, int(settings.SMS_TIMEOUT_SECONDS))
        endpoint = str(settings.SMS_ENDPOINT).strip() or "dysmsapi.aliyuncs.com"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"https://{endpoint}/", data=params)
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("调用阿里云短信接口失败: %s", exc)
            raise SmsDeliveryError("短信发送失败") from exc

        if data.get("Code") != "OK":
            # 错误码（如 isv.BUSINESS_LIMIT_CONTROL / isv.SMS_SIGNATURE_ILLEGAL）入日志，
            # 不外泄给客户端（统一文案，防探测）
            logger.error("阿里云短信发送被拒绝: Code=%s Message=%s", data.get("Code"), data.get("Message"))
            raise SmsDeliveryError("短信发送失败")

    def _sign(self, params: dict[str, str]) -> str:
        """RPC 风格 V1 签名：POST&%2F&<规范化查询串> 的 HMAC-SHA1（secret + '&'）。"""
        canonicalized = "&".join(
            f"{_percent_encode(key)}={_percent_encode(params[key])}" for key in sorted(params)
        )
        string_to_sign = "POST&%2F&" + _percent_encode(canonicalized)
        secret = str(settings.SMS_ACCESS_KEY_SECRET) + "&"
        digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
        return base64.b64encode(digest).decode("ascii")
