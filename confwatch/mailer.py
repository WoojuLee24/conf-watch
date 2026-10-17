"""SMTP 메일 발송. 계정 정보는 환경변수로만 받는다."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

def settings(cfg: dict) -> dict:
    """config.yaml 의 mail 섹션 + 환경변수(우선). 비밀번호는 환경변수로만."""
    env = os.environ.get
    return {
        "host": env("SMTP_HOST") or cfg.get("smtp_host", ""),
        "port": int(env("SMTP_PORT") or cfg.get("smtp_port", 587)),
        "user": env("SMTP_USER") or cfg.get("smtp_user", ""),
        "password": env("SMTP_PASS", ""),
        "to": [x.strip() for x in (env("MAIL_TO") or cfg.get("to", "")).split(",") if x.strip()],
    }


def missing(st: dict) -> list[str]:
    names = {"host": "SMTP_HOST(smtp_host)", "user": "SMTP_USER(smtp_user)", "password": "SMTP_PASS", "to": "MAIL_TO(to)"}
    return [names[k] for k in names if not st[k]]


def send(subject: str, html_body: str, text_body: str, st: dict) -> None:
    if missing(st):
        raise RuntimeError(f"메일 설정 누락: {', '.join(missing(st))}")
    host, port, user, pw, to = st["host"], st["port"], st["user"], st["password"], st["to"]
    sender = user

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
