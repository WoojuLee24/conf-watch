"""SMTP 메일 발송. 계정 정보는 환경변수로만 받는다."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

REQUIRED = ("SMTP_HOST", "SMTP_USER", "SMTP_PASS")


def configured() -> bool:
    return all(os.environ.get(k) for k in REQUIRED)


def recipients(default: str = "") -> list[str]:
    return [x.strip() for x in (os.environ.get("MAIL_TO") or default).split(",") if x.strip()]


def send(subject: str, html_body: str, text_body: str, to: list[str]) -> None:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"메일 환경변수 누락: {', '.join(missing)}")
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
    user, pw = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    if not to:
        raise RuntimeError("받는 사람 없음: config.yaml mail.to 또는 MAIL_TO")
    sender = os.environ.get("MAIL_FROM") or user

    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(to)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, pw)
            s.sendmail(sender, to, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.sendmail(sender, to, msg.as_string())
    log.info("메일 발송 완료 → %s", ", ".join(to))
