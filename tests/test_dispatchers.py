"""Unit test for SmtpDispatcher._send: STARTTLS+login only when credentials
are configured, so the unauthenticated Mailpit path stays byte-identical."""

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from jan_setu.config import Settings
from jan_setu.pipeline.dispatchers import SmtpDispatcher


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_send_skips_auth_when_no_username_configured():
    dispatcher = SmtpDispatcher(_settings())
    smtp = MagicMock()
    with patch("smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = smtp
        dispatcher._send(EmailMessage())
    smtp.starttls.assert_not_called()
    smtp.login.assert_not_called()
    smtp.send_message.assert_called_once()


def test_send_starttls_and_logs_in_when_username_configured():
    dispatcher = SmtpDispatcher(
        _settings(smtp_username="ocid1.user.oc1..x", smtp_password="secret")
    )
    smtp = MagicMock()
    with patch("smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = smtp
        dispatcher._send(EmailMessage())
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("ocid1.user.oc1..x", "secret")
    smtp.send_message.assert_called_once()
