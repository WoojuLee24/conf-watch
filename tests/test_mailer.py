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
    for k, v in {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "bot@example.com", "SMTP_PASS": "app-password",
                 }.items():
        monkeypatch.setenv(k, v)
    assert mailer.configured()
    monkeypatch.delenv("MAIL_TO", raising=False)
    to = mailer.recipients("a@example.com, b@example.com")
    mailer.send("[conf-watch] 테스트", "<b>본문</b>", "본문", to)
    sender, to, raw = FakeSMTP.sent[-1]
    assert to == ["a@example.com", "b@example.com"]
    msg = email.message_from_string(raw)
    assert str(email.header.make_header(email.header.decode_header(msg["Subject"]))) == "[conf-watch] 테스트"
    assert [p.get_content_type() for p in msg.get_payload()] == ["text/plain", "text/html"]
