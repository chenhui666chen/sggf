"""
邮件发送服务
"""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailServiceNotConfiguredError(RuntimeError):
    """邮件服务未配置。"""


class EmailDeliveryError(RuntimeError):
    """邮件发送失败。"""


class EmailService:
    """基于 SMTP 的邮件发送服务。"""

    def is_configured(self) -> bool:
        return bool(str(settings.SMTP_HOST).strip()) and bool(str(settings.SMTP_FROM_EMAIL).strip())

    async def send_password_reset_code(self, to_email: str, code: str) -> None:
        if not self.is_configured():
            raise EmailServiceNotConfiguredError("邮件服务未配置")

        try:
            await asyncio.to_thread(self._send_password_reset_code_sync, to_email, code)
        except EmailServiceNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("发送找回密码邮件失败: %s", exc)
            raise EmailDeliveryError("发送找回密码邮件失败") from exc

    def _build_password_reset_message(self, to_email: str, code: str) -> EmailMessage:
        app_name = str(settings.APP_NAME).strip() or "拾光工坊"
        from_name = str(settings.SMTP_FROM_NAME).strip() or app_name
        expires_minutes = max(1, settings.PASSWORD_RESET_CODE_TTL_SECONDS // 60)

        message = EmailMessage()
        message["Subject"] = f"{app_name} 密码重置验证码"
        message["From"] = formataddr((from_name, settings.SMTP_FROM_EMAIL))
        message["To"] = to_email
        message.set_content(
            "\n".join(
                [
                    f"您正在重置 {app_name} 账户密码。",
                    f"本次验证码为：{code}",
                    f"验证码 {expires_minutes} 分钟内有效，请勿泄露给他人。",
                    "如果这不是您的操作，请忽略此邮件。",
                ]
            )
        )
        message.add_alternative(
            f"""
            <html>
              <body style="margin:0;padding:24px;background:#f4f7fb;font-family:'Segoe UI',sans-serif;color:#1f2937;">
                <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 16px 40px rgba(15,23,42,0.08);">
                  <div style="padding:28px 32px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#ffffff;">
                    <div style="font-size:24px;font-weight:700;">{app_name}</div>
                    <div style="margin-top:8px;font-size:14px;opacity:0.92;">密码重置验证码</div>
                  </div>
                  <div style="padding:32px;">
                    <p style="margin:0 0 16px;font-size:15px;line-height:1.8;">您好，</p>
                    <p style="margin:0 0 20px;font-size:15px;line-height:1.8;">
                      我们收到了您的密码重置请求。请输入以下验证码完成身份校验：
                    </p>
                    <div style="margin:24px 0;padding:18px 20px;border-radius:14px;background:#f3f4ff;border:1px solid #dfe3ff;text-align:center;">
                      <div style="font-size:32px;letter-spacing:8px;font-weight:700;color:#4338ca;">{code}</div>
                    </div>
                    <p style="margin:0 0 12px;font-size:14px;line-height:1.8;color:#4b5563;">
                      验证码 <strong>{expires_minutes}</strong> 分钟内有效，仅可用于本次密码重置操作。
                    </p>
                    <p style="margin:0;font-size:14px;line-height:1.8;color:#4b5563;">
                      如果这不是您本人操作，请忽略此邮件，并检查账户安全。
                    </p>
                  </div>
                </div>
              </body>
            </html>
            """,
            subtype="html",
        )
        return message

    def _send_password_reset_code_sync(self, to_email: str, code: str) -> None:
        message = self._build_password_reset_message(to_email, code)
        timeout = max(1, int(settings.SMTP_TIMEOUT_SECONDS))
        host = str(settings.SMTP_HOST).strip()
        port = int(settings.SMTP_PORT)
        username = str(settings.SMTP_USERNAME).strip()
        password = str(settings.SMTP_PASSWORD)

        if not host:
            raise EmailServiceNotConfiguredError("SMTP_HOST 未配置")

        if settings.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            if settings.SMTP_USE_TLS:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
