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
            await asyncio.to_thread(
                self._send_message_sync, self._build_password_reset_message(to_email, code)
            )
        except EmailServiceNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("发送找回密码邮件失败: %s", exc)
            raise EmailDeliveryError("发送找回密码邮件失败") from exc

    async def send_email_verification_code(self, to_email: str, code: str) -> None:
        """发送邮箱验证码（P1-3.8：两步注册 / 登录态邮箱验证）。"""
        if not self.is_configured():
            raise EmailServiceNotConfiguredError("邮件服务未配置")

        try:
            await asyncio.to_thread(
                self._send_message_sync, self._build_email_verification_message(to_email, code)
            )
        except EmailServiceNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("发送邮箱验证码邮件失败: %s", exc)
            raise EmailDeliveryError("发送邮箱验证码邮件失败") from exc

    async def send_phone_unbind_notice(self, to_email: str, masked_phone: str) -> None:
        """手机号被新主人申诉接管后，通知原绑定用户（手机号字段已清空）。"""
        if not self.is_configured():
            raise EmailServiceNotConfiguredError("邮件服务未配置")

        try:
            await asyncio.to_thread(
                self._send_message_sync, self._build_phone_unbind_message(to_email, masked_phone)
            )
        except EmailServiceNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("发送手机号解绑通知邮件失败: %s", exc)
            raise EmailDeliveryError("发送手机号解绑通知邮件失败") from exc

    def _build_phone_unbind_message(self, to_email: str, masked_phone: str) -> EmailMessage:
        app_name = str(settings.APP_NAME).strip() or "拾光工坊"
        from_name = str(settings.SMTP_FROM_NAME).strip() or app_name

        message = EmailMessage()
        message["Subject"] = f"{app_name} 手机号解绑通知"
        message["From"] = formataddr((from_name, settings.SMTP_FROM_EMAIL))
        message["To"] = to_email
        message.set_content(
            "\n".join(
                [
                    f"您的 {app_name} 账号原绑定的手机号 {masked_phone} 已通过短信验证转移给新的持有人。",
                    "该手机号已从您的账号解除绑定，您的用户名、邮箱与密码不受影响，仍可正常登录。",
                    "如非您本人操作且认为有误，请尽快登录账号并联系客服。",
                ]
            )
        )
        return message

    def _build_email_verification_message(self, to_email: str, code: str) -> EmailMessage:
        app_name = str(settings.APP_NAME).strip() or "拾光工坊"
        from_name = str(settings.SMTP_FROM_NAME).strip() or app_name
        expires_minutes = max(1, settings.EMAIL_VERIFY_CODE_TTL_SECONDS // 60)

        message = EmailMessage()
        message["Subject"] = f"{app_name} 邮箱验证码"
        message["From"] = formataddr((from_name, settings.SMTP_FROM_EMAIL))
        message["To"] = to_email
        message.set_content(
            "\n".join(
                [
                    f"您正在使用邮箱验证 {app_name} 账户。",
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
                    <div style="margin-top:8px;font-size:14px;opacity:0.92;">邮箱验证码</div>
                  </div>
                  <div style="padding:32px;">
                    <p style="margin:0 0 16px;font-size:15px;line-height:1.8;">您好，</p>
                    <p style="margin:0 0 20px;font-size:15px;line-height:1.8;">
                      我们收到了您的邮箱验证请求。请输入以下验证码完成验证：
                    </p>
                    <div style="margin:24px 0;padding:18px 20px;border-radius:14px;background:#f3f4ff;border:1px solid #dfe3ff;text-align:center;">
                      <div style="font-size:32px;letter-spacing:8px;font-weight:700;color:#4338ca;">{code}</div>
                    </div>
                    <p style="margin:0 0 12px;font-size:14px;line-height:1.8;color:#4b5563;">
                      验证码 <strong>{expires_minutes}</strong> 分钟内有效，仅可用于本次邮箱验证操作。
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

    def _send_message_sync(self, message: EmailMessage) -> None:
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
