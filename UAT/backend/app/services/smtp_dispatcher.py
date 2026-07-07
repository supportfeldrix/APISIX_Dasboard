"""SMTP email dispatcher with retry logic for notification delivery."""
import asyncio
import logging
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from app.config import settings
from app.schemas.notifications import AlertContext, DeliveryResult

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2  # 2s, 4s, 8s


def _smtp_configured() -> bool:
    """Check if SMTP settings are minimally configured."""
    return bool(settings.SMTP_HOST and settings.SMTP_PORT and settings.SMTP_FROM_ADDRESS)


def _build_smtp_kwargs() -> dict:
    """Build connection kwargs for aiosmtplib."""
    kwargs = {
        "hostname": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "timeout": 10,
    }
    if settings.SMTP_USE_TLS:
        kwargs["start_tls"] = True
        # If SSL verification is disabled, create a permissive SSL context
        if not settings.SMTP_VERIFY_SSL:
            tls_context = ssl.create_default_context()
            tls_context.check_hostname = False
            tls_context.verify_mode = ssl.CERT_NONE
            kwargs["tls_context"] = tls_context
    if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
        kwargs["username"] = settings.SMTP_USERNAME
        kwargs["password"] = settings.SMTP_PASSWORD
    return kwargs


def _create_message(
    recipients: list[str], subject: str, body_html: str
) -> MIMEMultipart:
    """Create a MIME email message."""
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.SMTP_FROM_ADDRESS
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))
    return msg


def _is_auth_error(exc: Exception) -> bool:
    """Determine if an SMTP error is an authentication failure (non-retryable)."""
    error_str = str(exc).lower()
    # SMTP 535 = auth credentials invalid, 534 = auth mechanism issue
    if isinstance(exc, aiosmtplib.SMTPAuthenticationError):
        return True
    if "authentication" in error_str or "535" in error_str or "534" in error_str:
        return True
    return False


async def send_notification(
    recipients: list[str], subject: str, body_html: str
) -> DeliveryResult:
    """Send a notification email with retry logic.

    Retries up to 3 times with exponential backoff (2s, 4s, 8s).
    Auth failures are not retried.
    """
    if not _smtp_configured():
        return DeliveryResult(
            success=False,
            error_message="SMTP not configured",
            attempts=0,
        )

    smtp_kwargs = _build_smtp_kwargs()
    msg = _create_message(recipients, subject, body_html)
    last_error: Optional[str] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await aiosmtplib.send(msg, **smtp_kwargs)
            logger.info(
                "Email sent successfully to %s (attempt %d)", recipients, attempt
            )
            return DeliveryResult(success=True, attempts=attempt)

        except aiosmtplib.SMTPAuthenticationError as exc:
            # Auth failures are not transient — do not retry
            error_msg = f"SMTP authentication failed: {exc}"
            logger.error(error_msg)
            return DeliveryResult(
                success=False, error_message=error_msg, attempts=attempt
            )

        except (
            aiosmtplib.SMTPConnectError,
            aiosmtplib.SMTPConnectTimeoutError,
            aiosmtplib.SMTPServerDisconnected,
            asyncio.TimeoutError,
            OSError,
        ) as exc:
            last_error = f"SMTP delivery failed (attempt {attempt}/{MAX_RETRIES}): {exc}"
            logger.warning(last_error)

            if attempt < MAX_RETRIES:
                backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.info("Retrying in %ds...", backoff)
                await asyncio.sleep(backoff)

        except aiosmtplib.SMTPException as exc:
            # Catch-all for other SMTP errors
            if _is_auth_error(exc):
                error_msg = f"SMTP authentication failed: {exc}"
                logger.error(error_msg)
                return DeliveryResult(
                    success=False, error_message=error_msg, attempts=attempt
                )

            last_error = f"SMTP error (attempt {attempt}/{MAX_RETRIES}): {exc}"
            logger.warning(last_error)

            if attempt < MAX_RETRIES:
                backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.info("Retrying in %ds...", backoff)
                await asyncio.sleep(backoff)

    # All retries exhausted
    error_msg = f"Permanent delivery failure after {MAX_RETRIES} attempts: {last_error}"
    logger.error(
        "Permanent delivery failure for recipients %s: %s", recipients, last_error
    )
    return DeliveryResult(
        success=False, error_message=error_msg, attempts=MAX_RETRIES
    )


async def send_test_email(recipient: str) -> DeliveryResult:
    """Send a test email to verify SMTP connectivity.

    Uses a single attempt with a 10-second timeout (no retries).
    """
    if not _smtp_configured():
        return DeliveryResult(
            success=False,
            error_message="SMTP not configured: missing SMTP_HOST, SMTP_PORT, or SMTP_FROM_ADDRESS",
            attempts=0,
        )

    subject = "APISIX Dashboard - Test Email"
    body_html = """
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>APISIX Dashboard - Email Test</h2>
        <p>This is a test email from the APISIX Dashboard notification system.</p>
        <p>If you received this message, your SMTP configuration is working correctly.</p>
        <hr>
        <p style="color: #666; font-size: 12px;">
            Sent at: {timestamp}
        </p>
    </body>
    </html>
    """.format(timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    smtp_kwargs = _build_smtp_kwargs()
    msg = _create_message([recipient], subject, body_html)

    try:
        await aiosmtplib.send(msg, **smtp_kwargs)
        logger.info("Test email sent successfully to %s", recipient)
        return DeliveryResult(success=True, attempts=1)

    except aiosmtplib.SMTPAuthenticationError as exc:
        error_msg = f"SMTP authentication failed: {exc}"
        logger.error(error_msg)
        return DeliveryResult(success=False, error_message=error_msg, attempts=1)

    except (
        aiosmtplib.SMTPConnectError,
        aiosmtplib.SMTPConnectTimeoutError,
        aiosmtplib.SMTPServerDisconnected,
        asyncio.TimeoutError,
        OSError,
    ) as exc:
        error_msg = f"SMTP server unreachable: {exc}"
        logger.error(error_msg)
        return DeliveryResult(success=False, error_message=error_msg, attempts=1)

    except aiosmtplib.SMTPException as exc:
        error_msg = f"SMTP error: {exc}"
        logger.error(error_msg)
        return DeliveryResult(success=False, error_message=error_msg, attempts=1)


def format_alert_email(context: AlertContext) -> tuple[str, str]:
    """Format an alert notification email based on condition type.

    Returns:
        Tuple of (subject, body_html).
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    window_start = (
        context.evaluation_window_start.strftime("%Y-%m-%d %H:%M:%S UTC")
        if context.evaluation_window_start
        else "N/A"
    )
    window_end = (
        context.evaluation_window_end.strftime("%Y-%m-%d %H:%M:%S UTC")
        if context.evaluation_window_end
        else "N/A"
    )

    if context.condition_type == "JWT_FAILURE":
        subject = f"[ALERT] JWT Failure - {context.route_name} ({context.route_id})"
        details = _format_jwt_failure_details(context)

    elif context.condition_type == "UPSTREAM_ERROR":
        subject = f"[ALERT] Upstream Error - {context.route_name} ({context.route_id})"
        details = _format_upstream_error_details(context)

    elif context.condition_type == "CLIENT_ERROR":
        subject = f"[ALERT] Client Error (4xx) - {context.route_name} ({context.route_id})"
        details = _format_client_error_details(context)

    elif context.condition_type == "HIGH_ERROR_RATE":
        subject = f"[ALERT] High Error Rate - {context.route_name} ({context.route_id})"
        details = _format_high_error_rate_details(context)

    elif context.condition_type == "HEALTH_CHECK_FAILURE":
        subject = (
            f"[ALERT] Health Check Failure - {context.route_name} ({context.route_id})"
        )
        details = _format_health_check_failure_details(context)

    elif context.condition_type == "POD_HEALTH":
        subject = (
            f"[ALERT] Pod Unhealthy - {context.route_name}"
        )
        details = _format_pod_health_details(context)

    else:
        subject = f"[ALERT] {context.condition_type} - {context.route_name} ({context.route_id})"
        details = f"<p>Condition: {context.condition_type}</p><p>Metrics: {context.metric_values}</p>"

    # Normalize condition_type for display
    ctype = context.condition_type.value if hasattr(context.condition_type, 'value') else str(context.condition_type)

    body_html = _wrap_email_body(
        title=f"Alert: {ctype}",
        route_name=context.route_name,
        route_id=context.route_id,
        details=details,
        window_start=window_start,
        window_end=window_end,
        timestamp=timestamp,
    )

    return subject, body_html


def format_recovery_email(context: AlertContext) -> tuple[str, str]:
    """Format a recovery notification email.

    Returns:
        Tuple of (subject, body_html).
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    window_start = (
        context.evaluation_window_start.strftime("%Y-%m-%d %H:%M:%S UTC")
        if context.evaluation_window_start
        else "N/A"
    )
    window_end = (
        context.evaluation_window_end.strftime("%Y-%m-%d %H:%M:%S UTC")
        if context.evaluation_window_end
        else "N/A"
    )

    # Normalize condition_type to string value (handle enum or string)
    ctype = context.condition_type.value if hasattr(context.condition_type, 'value') else str(context.condition_type)

    subject = f"[RECOVERED] {ctype} - {context.route_name} ({context.route_id})"

    details = """
    <p style="color: #28a745; font-weight: bold;">✓ Route has recovered</p>
    <p>The previously triggered alert condition has returned to normal.</p>
    <table style="border-collapse: collapse; width: 100%;">
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Condition Type</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{condition_type}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Threshold</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{threshold}</td></tr>
    </table>
    """.format(
        condition_type=ctype,
        threshold=context.threshold,
    )

    body_html = _wrap_email_body(
        title=f"Recovery: {ctype}",
        route_name=context.route_name,
        route_id=context.route_id,
        details=details,
        window_start=window_start,
        window_end=window_end,
        timestamp=timestamp,
        is_recovery=True,
    )

    return subject, body_html


# --- Private formatting helpers ---


def _format_jwt_failure_details(context: AlertContext) -> str:
    """Format JWT failure alert details."""
    count_401 = context.metric_values.get("401_count", 0)
    count_403 = context.metric_values.get("403_count", 0)
    total = count_401 + count_403

    return """
    <table style="border-collapse: collapse; width: 100%;">
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">401 Responses</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{count_401}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">403 Responses</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{count_403}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Total JWT Failures</td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #dc3545; font-weight: bold;">{total}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Threshold</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{threshold}</td></tr>
    </table>
    """.format(
        count_401=count_401,
        count_403=count_403,
        total=total,
        threshold=context.threshold,
    )


def _format_upstream_error_details(context: AlertContext) -> str:
    """Format upstream error alert details with per-status-code breakdown."""
    # Read from "5xx_breakdown" dict (set by background_scheduler HWM logic)
    fivexx_breakdown = context.metric_values.get("5xx_breakdown", {})
    total_upstream_errors = context.metric_values.get("total_upstream_errors", 0)
    new_errors = context.metric_values.get("new_errors", 0)

    # Build breakdown rows dynamically for all 5xx codes present
    breakdown_rows = ""
    code_labels = {
        "500": "500 Internal Server Error",
        "502": "502 Bad Gateway",
        "503": "503 Service Unavailable",
        "504": "504 Gateway Timeout",
    }
    for code in sorted(fivexx_breakdown.keys()):
        count = fivexx_breakdown[code]
        label = code_labels.get(str(code), f"{code} Server Error")
        breakdown_rows += (
            f'<tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">{label}</td>'
            f'<td style="padding: 8px; border: 1px solid #ddd;">{count}</td></tr>\n'
        )

    # If no breakdown codes found, show a single "No breakdown available" row
    if not breakdown_rows:
        breakdown_rows = (
            '<tr><td style="padding: 8px; border: 1px solid #ddd;" colspan="2">'
            'No per-code breakdown available</td></tr>\n'
        )

    return f"""
    <table style="border-collapse: collapse; width: 100%;">
        {breakdown_rows}
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">New Errors (above HWM)</td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #dc3545; font-weight: bold;">{int(new_errors)}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Total Upstream Errors (cumulative)</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{int(total_upstream_errors)}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Threshold</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{context.threshold}</td></tr>
    </table>
    """


def _format_client_error_details(context: AlertContext) -> str:
    """Format client error (4xx) alert details with per-status-code breakdown."""
    fourxx_breakdown = context.metric_values.get("4xx_breakdown", {})
    total_client_errors = context.metric_values.get("total_client_errors", 0)
    new_errors = context.metric_values.get("new_errors", total_client_errors)

    # Build breakdown rows dynamically for all 4xx codes present
    breakdown_rows = ""
    for code in sorted(fourxx_breakdown.keys()):
        count = fourxx_breakdown[code]
        code_label = {
            "400": "400 Bad Request",
            "401": "401 Unauthorized",
            "403": "403 Forbidden",
            "404": "404 Not Found",
            "405": "405 Method Not Allowed",
            "408": "408 Request Timeout",
            "409": "409 Conflict",
            "413": "413 Payload Too Large",
            "429": "429 Too Many Requests",
            "499": "499 Client Closed Request",
        }.get(str(code), f"{code} Client Error")
        breakdown_rows += (
            f'<tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">{code_label}</td>'
            f'<td style="padding: 8px; border: 1px solid #ddd;">{count}</td></tr>\n'
        )

    return """
    <table style="border-collapse: collapse; width: 100%;">
        {breakdown_rows}
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Total Client Errors (4xx)</td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #dc3545; font-weight: bold;">{total_client_errors}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">New Errors (since last check)</td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #dc3545; font-weight: bold;">{new_errors}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Threshold</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{threshold}</td></tr>
    </table>
    """.format(
        breakdown_rows=breakdown_rows,
        total_client_errors=total_client_errors,
        new_errors=new_errors,
        threshold=context.threshold,
    )


def _format_high_error_rate_details(context: AlertContext) -> str:
    """Format high error rate alert details."""
    error_rate = context.metric_values.get("error_rate", 0.0)
    total_requests = context.metric_values.get("total_requests", 0)

    return """
    <table style="border-collapse: collapse; width: 100%;">
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Error Rate</td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #dc3545; font-weight: bold;">{error_rate:.2f}%</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Threshold</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{threshold}%</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Total Requests Evaluated</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{total_requests}</td></tr>
    </table>
    """.format(
        error_rate=error_rate,
        threshold=context.threshold,
        total_requests=total_requests,
    )


def _format_health_check_failure_details(context: AlertContext) -> str:
    """Format health check failure alert details."""
    consecutive_failures = context.metric_values.get("consecutive_failures", 0)
    last_error = context.metric_values.get("last_error", "Unknown")

    return """
    <table style="border-collapse: collapse; width: 100%;">
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Consecutive Failures</td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #dc3545; font-weight: bold;">{consecutive_failures}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Failure Threshold</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{threshold}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Last Error</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{last_error}</td></tr>
    </table>
    """.format(
        consecutive_failures=consecutive_failures,
        threshold=context.threshold,
        last_error=last_error,
    )


def _format_pod_health_details(context: AlertContext) -> str:
    """Format pod health alert details."""
    unhealthy_pod = context.metric_values.get("unhealthy_pod", "Unknown")
    reason = context.metric_values.get("reason", "Unknown")
    restart_count = context.metric_values.get("restart_count", 0)
    total_unhealthy = context.metric_values.get("total_unhealthy", 1)
    unhealthy_pods = context.metric_values.get("unhealthy_pods", [])

    pods_list = "<br>".join(unhealthy_pods) if unhealthy_pods else unhealthy_pod

    return """
    <table style="border-collapse: collapse; width: 100%;">
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Unhealthy Pod</td>
            <td style="padding: 8px; border: 1px solid #ddd; color: #dc3545; font-weight: bold;">{unhealthy_pod}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Reason</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{reason}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Restart Count</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{restart_count}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Restart Threshold</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{threshold}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Total Unhealthy Pods</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{total_unhealthy}</td></tr>
        <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Affected Pods</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{pods_list}</td></tr>
    </table>
    """.format(
        unhealthy_pod=unhealthy_pod,
        reason=reason,
        restart_count=restart_count,
        threshold=context.threshold,
        total_unhealthy=total_unhealthy,
        pods_list=pods_list,
    )


def _wrap_email_body(
    title: str,
    route_name: str,
    route_id: str,
    details: str,
    window_start: str,
    window_end: str,
    timestamp: str,
    is_recovery: bool = False,
) -> str:
    """Wrap alert/recovery details in a styled HTML email template."""
    header_color = "#28a745" if is_recovery else "#dc3545"
    header_label = "RECOVERED" if is_recovery else "ALERT"

    return """
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f8f9fa;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <div style="background-color: {header_color}; color: white; padding: 16px 24px;">
                <h2 style="margin: 0;">[{header_label}] {title}</h2>
            </div>
            <div style="padding: 24px;">
                <h3 style="margin-top: 0;">Route Information</h3>
                <table style="border-collapse: collapse; width: 100%; margin-bottom: 20px;">
                    <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Route Name</td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{route_name}</td></tr>
                    <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Route ID</td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{route_id}</td></tr>
                </table>

                <h3>Alert Details</h3>
                {details}

                <h3 style="margin-top: 20px;">Evaluation Window</h3>
                <table style="border-collapse: collapse; width: 100%;">
                    <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Window Start</td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{window_start}</td></tr>
                    <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Window End</td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{window_end}</td></tr>
                    <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Alert Timestamp</td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{timestamp}</td></tr>
                </table>
            </div>
            <div style="background-color: #f8f9fa; padding: 12px 24px; border-top: 1px solid #dee2e6;">
                <p style="margin: 0; color: #6c757d; font-size: 12px;">
                    This is an automated notification from the APISIX Dashboard.
                </p>
            </div>
        </div>
    </body>
    </html>
    """.format(
        header_color=header_color,
        header_label=header_label,
        title=title,
        route_name=route_name,
        route_id=route_id,
        details=details,
        window_start=window_start,
        window_end=window_end,
        timestamp=timestamp,
    )
