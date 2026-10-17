import email

from confwatch import mailer


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, pw):
        assert (user, pw) == ("bot@example.com", "app-password")

    def sendmail(self, sender, to, msg):
        FakeSMTP.sent.append((sender, to, msg))


def test_send(monkeypatch):
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "MAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    cfg = {"to": "a@example.com, b@example.com", "smtp_host": "smtp.example.com", "smtp_user": "bot@example.com"}
    monkeypatch.delenv("SMTP_PASS", raising=False)
    assert mailer.missing(mailer.settings(cfg)) == ["SMTP_PASS"]
    monkeypatch.setenv("SMTP_PASS", "app-password")
    st = mailer.settings(cfg)
    assert st["port"] == 587 and not mailer.missing(st)
    mailer.send("[conf-watch] 테스트", "<b>본문</b>", "본문", st)
    sender, to, raw = FakeSMTP.sent[-1]
    assert sender == "bot@example.com" and to == ["a@example.com", "b@example.com"]
    msg = email.message_from_string(raw)
    assert str(email.header.make_header(email.header.decode_header(msg["Subject"]))) == "[conf-watch] 테스트"
    assert [p.get_content_type() for p in msg.get_payload()] == ["text/plain", "text/html"]
