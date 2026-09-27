"""
SENDING MAIL WITHOUT LETTING MAIL BREAK THE APP.

A welcome message when someone joins, and a "you just signed in"
message each time they log in. That is the whole feature. The
interesting part is everything it deliberately refuses to do.

THE GOVERNING RULE: LOGIN MUST NEVER DEPEND ON THIS

Mail servers are slow, rate-limited and occasionally just down.
Gmail in particular can take several seconds to accept a message, and
refuses outright if the account's App Password was revoked. None of
that is the user's problem when they are trying to log in, so:

  - every send runs on a BACKGROUND thread. The login response is
    already on its way back to the browser before the mail server is
    even contacted.
  - every failure is swallowed and logged. There is no code path in
    which a mail problem turns into a failed login, a 500, or an
    error message on the screen.
  - with no SMTP settings configured, every function here quietly
    does nothing. A machine that has not set this up still runs the
    whole application; it just sends no mail.

WHAT NEVER LEAVES THE SERVER

The SMTP password is an App Password with full send rights on a real
mailbox. It is read from .env, used, and never returned, logged,
included in an exception message, or sent to the browser. The failure
descriptions below are written by hand for exactly that reason -
smtplib's own exception text can contain the credentials it tried.

WHY NOT A LIBRARY

smtplib is in Python's standard library, and this needs perhaps sixty
lines of it. Adding a dependency here would mean one more thing to
install on two laptops that have already drifted apart once.
"""

import html
import logging
import smtplib
import threading
from datetime import datetime
from email.message import EmailMessage

from backend import config


logger = logging.getLogger(__name__)


# How long to wait for the mail server before giving up. Short on
# purpose: this runs on a background thread, but a thread stuck for
# minutes on a dead server is still a leak.
SMTP_TIMEOUT_SECONDS = 20


def _sender():
    """
    The From address. Defaults to the mailbox we authenticate as,
    because most providers - Gmail certainly - reject a From address
    that isn't the account sending it.
    """
    return config.SMTP_FROM_EMAIL or config.SMTP_USERNAME


def _describe_failure(error):
    """
    A short, safe description of why a send failed.

    Deliberately built from the EXCEPTION TYPE rather than its text.
    smtplib puts the server's reply - which can echo the username, and
    in some misconfigurations the credentials - into str(error), and
    this string goes into a log file that gets pasted into chat windows
    when something goes wrong.
    """
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return (
            "the mail server rejected the username or password "
            "(for Gmail this usually means the App Password was "
            "revoked, or an ordinary account password was used "
            "instead of an App Password)"
        )

    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "the mail server refused the recipient address"

    if isinstance(error, smtplib.SMTPSenderRefused):
        return "the mail server refused the sender address"

    if isinstance(error, smtplib.SMTPConnectError):
        return "could not connect to the mail server"

    if isinstance(error, smtplib.SMTPServerDisconnected):
        return "the mail server closed the connection"

    if isinstance(error, TimeoutError):
        return "the mail server did not respond in time"

    if isinstance(error, OSError):
        return "the mail server could not be reached over the network"

    return f"an unexpected {type(error).__name__} while sending"


def send_email(to_address, subject, text_body, html_body=None):
    """
    Sends one message and waits for it. Returns (sent, detail).

    `detail` is a safe sentence for a log, never the raw server reply.
    This is the blocking version; normal callers want send_async().
    """
    if not config.email_configured():
        return False, "email is not configured on this machine"

    if not to_address:
        return False, "no recipient address"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{config.SMTP_FROM_NAME} <{_sender()}>"
    message["To"] = to_address
    message.set_content(text_body)

    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        if config.SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(
                config.SMTP_HOST, config.SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS
            )
        else:
            server = smtplib.SMTP(
                config.SMTP_HOST, config.SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS
            )

        with server:
            if not config.SMTP_USE_SSL:
                server.starttls()

            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.send_message(message)

    except Exception as error:  # noqa: BLE001 - nothing here may escape
        detail = _describe_failure(error)
        logger.warning("Could not send '%s' to %s: %s", subject, to_address, detail)
        return False, detail

    logger.info("Sent '%s' to %s", subject, to_address)
    return True, "sent"


def send_async(to_address, subject, text_body, html_body=None):
    """
    Hands the send to a background thread and returns immediately.

    Returns the Thread so tests can wait for it. Application code
    ignores the return value - that is the entire point.
    """
    if not config.email_configured():
        return None

    thread = threading.Thread(
        target=send_email,
        args=(to_address, subject, text_body, html_body),
        daemon=True,
        name=f"email-{subject[:20]}",
    )
    thread.start()
    return thread


# ============================================================
# THE TWO MESSAGES
# ============================================================

def _shell(heading, paragraphs):
    """
    One small HTML layout for both messages, with every piece of
    user-supplied text escaped. A name is chosen by the user, so it is
    untrusted input being placed into a document - the same rule that
    applies to a web page applies to an HTML email.
    """
    body = "".join(
        f'<p style="margin:0 0 14px;line-height:1.55;">{paragraph}</p>'
        for paragraph in paragraphs
    )

    return f"""\
<html>
  <body style="margin:0;padding:24px;background:#f5f4f2;
               font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
               color:#20201e;">
    <div style="max-width:520px;margin:0 auto;background:#ffffff;
                border:1px solid #e5e3df;border-radius:12px;padding:28px;">
      <h1 style="margin:0 0 18px;font-size:20px;font-weight:600;">{heading}</h1>
      {body}
      <p style="margin:24px 0 0;padding-top:16px;border-top:1px solid #e5e3df;
                font-size:13px;color:#6b6862;">
        Wardrobe AI
      </p>
    </div>
  </body>
</html>"""


def send_welcome_email(name, email_address):
    """
    Sent once, when the account is created.
    """
    safe_name = html.escape((name or "there").strip() or "there")
    plain_name = (name or "there").strip() or "there"

    subject = "Welcome to Wardrobe AI"

    text_body = (
        f"Hi {plain_name},\n\n"
        "Your Wardrobe AI account is ready.\n\n"
        "Add a few clothes to your wardrobe and the app will start "
        "suggesting outfits for the weather where you are and for the "
        "occasion you pick.\n\n"
        "Your wardrobe is stored against this email address, so you can "
        "sign in from any computer and find the same clothes there.\n\n"
        "- Wardrobe AI\n"
    )

    html_body = _shell(
        f"Welcome, {safe_name}",
        [
            "Your Wardrobe AI account is ready.",
            "Add a few clothes to your wardrobe and the app will start "
            "suggesting outfits for the weather where you are and for the "
            "occasion you pick.",
            "Your wardrobe is stored against this email address, so you can "
            "sign in from any computer and find the same clothes there.",
        ],
    )

    return send_async(email_address, subject, text_body, html_body)


def send_signin_email(name, email_address, when=None):
    """
    Sent on a successful login.

    It doubles as a security notice - an account holder who did not
    just sign in learns that someone else did - which is why it names
    the time and says what to do about it.
    """
    safe_name = html.escape((name or "there").strip() or "there")
    plain_name = (name or "there").strip() or "there"

    when = when or datetime.now()
    stamp = when.strftime("%d %B %Y at %I:%M %p")

    subject = "Welcome back to Wardrobe AI"

    text_body = (
        f"Hi {plain_name},\n\n"
        f"You signed in to Wardrobe AI on {stamp}.\n\n"
        "Your wardrobe and saved trips are ready.\n\n"
        "If this wasn't you, change your password.\n\n"
        "- Wardrobe AI\n"
    )

    html_body = _shell(
        f"Welcome back, {safe_name}",
        [
            f"You signed in to Wardrobe AI on {html.escape(stamp)}.",
            "Your wardrobe and saved trips are ready.",
            "If this wasn&#39;t you, change your password.",
        ],
    )

    return send_async(email_address, subject, text_body, html_body)


def send_password_reset_code(name, email_address, code, minutes):
    """
    Sent when someone uses "Forgot password". Carries the 6-digit
    code only - never a password.
    """
    safe_name = html.escape((name or "there").strip() or "there")
    plain_name = (name or "there").strip() or "there"

    subject = f"Your Wardrobe AI reset code: {code}"

    text_body = (
        f"Hi {plain_name},\n\n"
        f"Your password reset code is: {code}\n\n"
        f"It expires in {minutes} minutes.\n\n"
        "If you didn't ask to reset your password, ignore this email - "
        "your password stays the same.\n\n"
        "- Wardrobe AI\n"
    )

    html_body = _shell(
        f"Reset your password, {safe_name}",
        [
            "Enter this code in the app to choose a new password:",
            f'<span style="font-size:28px;font-weight:700;letter-spacing:6px;">{code}</span>',
            f"It expires in {minutes} minutes.",
            "If you didn&#39;t ask to reset your password, ignore this email - "
            "your password stays the same.",
        ],
    )

    return send_async(email_address, subject, text_body, html_body)
