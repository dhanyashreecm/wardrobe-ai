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


# ============================================================
# EMAIL VERIFICATION + LOGIN NOTIFICATION
# ============================================================

BRAND = "Wardrobe-AI"


def _branded(heading, inner_html, footer="Wardrobe-AI Security Team"):
    """
    Branded layout for security mail. `inner_html` must already be
    escaped by the caller - every value in it that came from a user or
    a request header goes through html.escape first.
    """
    return f"""\
<html>
  <body style="margin:0;padding:24px;background:#f5f0ea;
               font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
               color:#20201e;">
    <div style="max-width:540px;margin:0 auto;background:#ffffff;
                border:1px solid #e8dfd5;border-radius:12px;overflow:hidden;">
      <div style="background:#3a2a1f;color:#ffffff;padding:18px 28px;
                  font-size:18px;font-weight:700;letter-spacing:.3px;">
        &#128090; {BRAND}
      </div>
      <div style="padding:28px;">
        <h1 style="margin:0 0 18px;font-size:20px;font-weight:600;">{heading}</h1>
        {inner_html}
        <p style="margin:24px 0 0;padding-top:16px;border-top:1px solid #e8dfd5;
                  font-size:13px;color:#6b6862;">
          Thank you,<br>{html.escape(footer)}
        </p>
      </div>
    </div>
  </body>
</html>"""


def send_verification_code(name, email_address, code, minutes):
    """
    Sent at registration (and on "resend code"). Carries the 6-digit
    code only - never the password.
    """
    plain_name = (name or "there").strip() or "there"
    safe_name = html.escape(plain_name)
    safe_code = html.escape(str(code))

    subject = f"Verify your {BRAND} email - code {code}"

    text_body = (
        f"Hi {plain_name},\n\n"
        f"Welcome to {BRAND}! To finish creating your account, enter this "
        f"verification code in the app:\n\n    {code}\n\n"
        f"The code expires in {minutes} minutes.\n\n"
        f"If you didn't create a {BRAND} account, you can ignore this email - "
        "no account will be activated without this code.\n\n"
        f"Thank you,\n{BRAND} Team\n"
    )

    inner = (
        f'<p style="margin:0 0 14px;line-height:1.55;">Hi {safe_name},</p>'
        f'<p style="margin:0 0 14px;line-height:1.55;">To finish creating your '
        f'account, enter this verification code in the app:</p>'
        f'<p style="margin:0 0 14px;font-size:30px;font-weight:700;letter-spacing:8px;">'
        f'{safe_code}</p>'
        f'<p style="margin:0 0 14px;line-height:1.55;">The code expires in {int(minutes)} minutes.</p>'
        f'<p style="margin:0 0 14px;line-height:1.55;color:#6b6862;">If you didn&#39;t '
        f'create a {BRAND} account, you can ignore this email - no account will be '
        f'activated without this code.</p>'
    )

    return send_async(email_address, subject, text_body,
                      _branded("Verify your email address", inner, f"{BRAND} Team"))


def build_login_notification(name, details):
    """
    (subject, text_body, html_body) for a successful login.

    `details` comes from login_context.describe_login(). It never
    contains - and this function never adds - the password or the
    login token.
    """
    plain_name = (name or "").strip()
    greeting = f"Hello {plain_name}," if plain_name else "Hello,"
    location = details.get("location") or "Not available"

    rows = [
        ("Date", details.get("date") or "Unknown"),
        ("Time", details.get("time") or "Unknown"),
        ("Device", details.get("device") or "Unknown device"),
        ("Browser", details.get("browser") or "Unknown browser"),
        ("Location", location),
    ]
    if details.get("ip"):
        rows.append(("IP address", details["ip"]))

    subject = f"New Login to Your {BRAND} Account"

    text_body = (
        f"{greeting}\n\n"
        f"Your {BRAND} account was successfully accessed.\n\n"
        "Login details:\n"
        + "".join(f"  - {label}: {value}\n" for label, value in rows)
        + "\nIf this was you, no action is required.\n\n"
        "If you don't recognize this login, please change your password "
        "immediately (use 'Forgot password' on the login page) and secure "
        "your account.\n\n"
        f"Thank you,\n{BRAND} Security Team\n"
    )

    table = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#6b6862;white-space:nowrap;'
        f'vertical-align:top;">{html.escape(label)}</td>'
        f'<td style="padding:6px 0;font-weight:600;">{html.escape(str(value))}</td></tr>'
        for label, value in rows
    )

    inner = (
        f'<p style="margin:0 0 14px;line-height:1.55;">{html.escape(greeting)}</p>'
        f'<p style="margin:0 0 14px;line-height:1.55;">Your {BRAND} account was '
        f'successfully accessed.</p>'
        f'<table style="border-collapse:collapse;margin:0 0 18px;font-size:14px;">{table}</table>'
        f'<p style="margin:0 0 14px;line-height:1.55;">If this was you, no action is required.</p>'
        f'<div style="margin:0 0 6px;padding:12px 14px;background:#fdf1ea;'
        f'border-left:4px solid #c1694f;border-radius:6px;line-height:1.5;">'
        f'<strong>Don&#39;t recognize this login?</strong> Change your password '
        f'immediately using <em>Forgot password</em> on the login page, and secure '
        f'your account.</div>'
    )

    return subject, text_body, _branded("New login to your account", inner)


def send_login_notification(name, email_address, details):
    """
    Background send - a slow or broken mail server can never delay or
    fail the login itself (see the module docstring).
    """
    subject, text_body, html_body = build_login_notification(name, details)
    return send_async(email_address, subject, text_body, html_body)
