"""
Email sender via Gmail SMTP (SSL).
Credentials come from environment variables:
  GMAIL_USER, GMAIL_APP_PASSWORD, REPORT_EMAIL
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_report_email(subject: str, html_body: str) -> bool:
    """Send the HTML report via Gmail. Returns True on success."""
    user = os.environ.get("GMAIL_USER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("REPORT_EMAIL")

    missing = [k for k, v in {
        "GMAIL_USER": user,
        "GMAIL_APP_PASSWORD": app_password,
        "REPORT_EMAIL": recipient,
    }.items() if not v]
    if missing:
        logger.error("Missing email env vars: %s", ", ".join(missing))
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(user, app_password)
            server.sendmail(user, [recipient], msg.as_string())
        logger.info("Report email sent to %s", recipient)
        return True
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return False
