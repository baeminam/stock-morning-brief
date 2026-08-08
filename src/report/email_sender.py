"""
Email sender via Gmail SMTP (SSL).
Credentials come from environment variables:
  GMAIL_USER, GMAIL_APP_PASSWORD, REPORT_EMAIL
"""

import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


def send_report_email(
    subject: str,
    html_body: str,
    recipients: list[str] | None = None,
    text_body: str | None = None,
    attachments: list[str | Path] | None = None,
) -> bool:
    """Send the report via Gmail (plain text + HTML multipart). Returns True on success.

    recipients: explicit list of addresses. When None, falls back to the
    REPORT_EMAIL env var (comma/semicolon separated).
    """
    user = os.environ.get("GMAIL_USER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")

    if recipients is None:
        raw = os.environ.get("REPORT_EMAIL", "")
        recipients = [e.strip() for e in raw.replace(";", ",").split(",") if e.strip()]

    missing = [k for k, v in {
        "GMAIL_USER": user,
        "GMAIL_APP_PASSWORD": app_password,
    }.items() if not v]
    if missing:
        logger.error("Missing email env vars: %s", ", ".join(missing))
        return False
    if not recipients:
        logger.error("No recipients: set REPORT_EMAIL or config/recipients.txt")
        return False

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)

    # plain text first, HTML last (clients prefer the last supported part)
    body = MIMEMultipart("alternative")
    body.attach(MIMEText(text_body or "HTML 형식의 리포트입니다. HTML을 지원하는 메일 앱에서 확인해 주세요.", "plain", "utf-8"))
    body.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(body)

    for path in attachments or []:
        path = Path(path)
        if not path.exists():
            continue
        part = MIMEApplication(path.read_bytes(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=path.name)
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(user, app_password)
            server.sendmail(user, recipients, msg.as_string())
        logger.info("Report email sent to %d recipient(s): %s", len(recipients), ", ".join(recipients))
        return True
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return False
