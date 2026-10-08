"""
GMAIL SMTP DIAGNOSTIC - finds the exact stage where sending fails.

    python -m backend.smtp_diagnose
    python -m backend.smtp_diagnose --send someone@gmail.com

Uses the SAME settings as the app (backend/config.py, which reads .env)
and tests both secure methods Gmail offers, one stage at a time:

    587 STARTTLS : TCP connection + SMTP greeting -> EHLO -> STARTTLS
                   (TLS handshake) -> certificate validation + hostname
                   -> EHLO after TLS -> AUTH (App Password)
    465 SSL      : TCP connection -> TLS handshake -> certificate
                   validation + hostname -> SMTP greeting -> EHLO
                   -> AUTH (App Password)

With --send EMAIL it then sends ONE diagnostic email, inside a session
that has already authenticated successfully.

Exit status: 0 = the app's configured method works (and the email was
accepted, if --send was used); 1 = a stage failed; 2 = missing settings.

Safety
  * The App Password is never printed. smtplib's debug mode is not used
    (it prints the AUTH exchange). Every error message is scrubbed of
    the password before printing.
  * Windows environment variables that override .env are reported by
    NAME only, never by value.
  * Nothing is changed: no .env edits, no database access, and the
    application's own email code (email_service.py) is not used or
    modified.
"""

import os
import socket
import ssl
import smtplib
import sys
import time
from email.message import EmailMessage

# Snapshot BEFORE config.py loads .env: anything already here came from
# Windows' environment, and config.py lets those beat .env.
_FROM_WINDOWS_ENV = sorted(k for k in os.environ if k.startswith("SMTP_"))

from backend import config  # noqa: E402

HOST = config.SMTP_HOST
TIMEOUT = 20


# ------------------------------------------------------------------
# Redaction
# ------------------------------------------------------------------

def _secrets():
    values = set()
    for raw in (config.SMTP_PASSWORD, os.environ.get("SMTP_PASSWORD", "")):
        if raw:
            values.add(raw)
            values.add("".join(raw.split()))
    return [v for v in values if v]


def scrub(text):
    text = " ".join(str(text).split())
    for secret in _secrets():
        text = text.replace(secret, "[redacted]")
    return text[:300]


def describe(error):
    code = getattr(error, "smtp_code", None)
    msg = getattr(error, "smtp_error", None)
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", "replace")
    if code is None and not msg:
        return f"{type(error).__name__}: {scrub(error) or '(no message)'}"
    return f"{type(error).__name__}: {code} {scrub(msg)}"


# ------------------------------------------------------------------
# One method, stage by stage
# ------------------------------------------------------------------

class Result:
    def __init__(self, name, port):
        self.name = name
        self.port = port
        self.failed_at = None       # stage category, e.g. "authentication"
        self.detail = ""
        self.issuer = ""
        self.sent = None            # None = not attempted, True/False

    @property
    def works(self):
        return self.failed_at is None


def ok(stage, info=""):
    print(f"  [ OK ] {stage}" + (f" - {info}" if info else ""))


def fail(result, category, stage, detail):
    result.failed_at = category
    result.detail = detail if isinstance(detail, str) else describe(detail)
    print(f"  [FAIL] {stage} - {result.detail}")
    print(f"         => failure is at: {category.upper()}")
    return result


def _context():
    # Full verification: trusted chain AND certificate hostname must match.
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _report_cert(result, sock):
    cert = sock.getpeercert() or {}
    issuer = dict(x[0] for x in cert.get("issuer", ()))
    names = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    result.issuer = f"{issuer.get('organizationName', '?')} / {issuer.get('commonName', '?')}"
    ok("Certificate validation", f"trusted, issued by '{result.issuer}'")
    match = next((n for n in names if n == HOST or
                  (n.startswith("*.") and HOST.endswith(n[1:]))), None)
    ok("Certificate hostname", f"'{HOST}' matches certificate name '{match or names[:1]}'")
    if "google" not in result.issuer.lower():
        print("  [WARN] Certificate is NOT issued by Google - antivirus e-mail scanning or a "
              "proxy on this PC/network is intercepting SMTP.")


def _tls_failure(result, error, stage):
    if isinstance(error, ssl.SSLCertVerificationError):
        what = error.verify_message or str(error)
        if "hostname" in what.lower() or "match" in what.lower():
            return fail(result, "certificate validation", "Certificate hostname",
                        f"certificate does not match '{HOST}' ({scrub(what)})")
        return fail(result, "certificate validation", "Certificate validation",
                    f"certificate NOT trusted ({scrub(what)}) - something between this "
                    "PC and Gmail is intercepting the connection")
    return fail(result, "STARTTLS/TLS", stage, error)


def _ehlo(server, result, stage, category):
    try:
        code, _ = server.ehlo()
    except Exception as error:  # noqa: BLE001
        fail(result, category, stage, error)
        return False
    if code != 250:
        fail(result, category, stage, f"server replied {code}")
        return False
    return True


def _auth_and_send(server, result, send_to):
    if not server.has_extn("auth"):
        fail(result, "authentication", "SMTP AUTH", "server did not offer AUTH")
        return
    ok("EHLO after TLS", "AUTH " + server.esmtp_features.get("auth", "").strip())
    try:
        server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
    except Exception as error:  # noqa: BLE001
        fail(result, "authentication", "SMTP AUTH (App Password)", error)
        if isinstance(error, smtplib.SMTPAuthenticationError):
            print("         Gmail rejected the login: create a new App Password "
                  "(Google Account > Security > 2-Step Verification > App passwords) "
                  "and save it with: python -m backend.set_secret SMTP_PASSWORD")
        return
    ok("SMTP AUTH (App Password)", "235 accepted")

    if not send_to:
        return
    message = EmailMessage()
    message["Subject"] = f"Wardrobe AI SMTP diagnostic (port {result.port})"
    message["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL or config.SMTP_USERNAME}>"
    message["To"] = send_to
    message.set_content(
        f"This diagnostic email was sent by Wardrobe AI through {HOST}:{result.port}.\n"
        "If you can read this, password-reset codes can reach this inbox.\n")
    try:
        refused = server.send_message(message, to_addrs=[send_to])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    except Exception as error:  # noqa: BLE001
        result.sent = False
        fail(result, "sending", f"Send to {send_to}", error)
        return
    result.sent = True
    ok(f"Send to {send_to}", "Gmail accepted the message (250)")


def _close(server):
    if server is None:
        return
    try:
        server.quit()
    except Exception:  # noqa: BLE001
        server.close()


def test_starttls(send_to=None):
    result = Result(f"{HOST}:587 STARTTLS", 587)
    print(f"\n=== {result.name} ===")
    server = None
    try:
        start = time.monotonic()
        try:
            server = smtplib.SMTP(timeout=TIMEOUT)
            code, banner = server.connect(HOST, 587)
        except Exception as error:  # noqa: BLE001
            return fail(result, "TCP connection", "TCP connection + SMTP greeting", error)
        ok("TCP connection + SMTP greeting",
           f"{code} {scrub(banner.decode(errors='replace'))} ({time.monotonic() - start:.1f}s)")

        if not _ehlo(server, result, "EHLO", "TCP connection"):
            return result
        if not server.has_extn("starttls"):
            return fail(result, "STARTTLS/TLS", "EHLO", "server did not offer STARTTLS")
        ok("EHLO", f"as '{server.local_hostname}', STARTTLS offered")

        try:
            server.starttls(context=_context())
        except Exception as error:  # noqa: BLE001
            return _tls_failure(result, error, "STARTTLS / TLS handshake")
        ok("STARTTLS / TLS handshake", f"{server.sock.version()}, {server.sock.cipher()[0]}")
        _report_cert(result, server.sock)

        if not _ehlo(server, result, "EHLO after TLS", "STARTTLS/TLS"):
            return result
        _auth_and_send(server, result, send_to)
        return result
    finally:
        _close(server)


def test_ssl(send_to=None):
    result = Result(f"{HOST}:465 SSL", 465)
    print(f"\n=== {result.name} ===")
    server = None
    raw = None
    try:
        start = time.monotonic()
        try:
            raw = socket.create_connection((HOST, 465), timeout=TIMEOUT)
        except Exception as error:  # noqa: BLE001
            return fail(result, "TCP connection", "TCP connection", error)
        ok("TCP connection", f"{time.monotonic() - start:.1f}s")
        try:
            tls = _context().wrap_socket(raw, server_hostname=HOST)
        except Exception as error:  # noqa: BLE001
            return _tls_failure(result, error, "TLS handshake")
        raw = None
        ok("TLS handshake", f"{tls.version()}, {tls.cipher()[0]}")
        _report_cert(result, tls)
        tls.close()

        # Now the real SMTP-over-SSL session (same checks, via smtplib).
        try:
            server = smtplib.SMTP_SSL(HOST, 465, timeout=TIMEOUT, context=_context())
        except Exception as error:  # noqa: BLE001
            if isinstance(error, ssl.SSLError):
                return _tls_failure(result, error, "TLS handshake")
            return fail(result, "TCP connection", "SMTP greeting", error)
        ok("SMTP greeting", "220 received")
        if not _ehlo(server, result, "EHLO", "STARTTLS/TLS"):
            return result
        _auth_and_send(server, result, send_to)
        return result
    finally:
        if raw is not None:
            raw.close()
        _close(server)


# ------------------------------------------------------------------

def main():
    send_to = None
    if "--send" in sys.argv:
        i = sys.argv.index("--send")
        send_to = sys.argv[i + 1].strip().lower() if i + 1 < len(sys.argv) else ""
        if "@" not in send_to:
            print("Usage: python -m backend.smtp_diagnose [--send someone@gmail.com]")
            return 2

    password = config.SMTP_PASSWORD or ""
    print("--- Configuration Wardrobe AI is using (secrets hidden) ---")
    print(f"SMTP_HOST     : {HOST}")
    print(f"SMTP_PORT     : {config.SMTP_PORT} ({'SSL' if config.SMTP_USE_SSL else 'STARTTLS'})")
    print(f"SMTP_USERNAME : {config.SMTP_USERNAME or '(missing)'}")
    shape = "16 letters - App Password format" if len(password) == 16 and password.isalpha() \
        else "NOT the 16-letter App Password format"
    print(f"SMTP_PASSWORD : {'set (' + shape + ')' if password else '(missing)'}")
    if _FROM_WINDOWS_ENV:
        print("Windows env   : OVERRIDES .env for: " + ", ".join(_FROM_WINDOWS_ENV)
              + "  (values hidden; remove them or make them match .env)")
    else:
        print("Windows env   : no SMTP_* variables - values come from .env")
    print(f"This PC       : Python {sys.version.split()[0]}, {ssl.OPENSSL_VERSION}")

    if not (config.SMTP_USERNAME and password):
        print("\nSMTP_USERNAME / SMTP_PASSWORD missing - set them with "
              "python -m backend.set_secret SMTP_PASSWORD")
        return 2

    try:
        addrs = sorted({a[4][0] for a in socket.getaddrinfo(HOST, 587, proto=socket.IPPROTO_TCP)})
        print(f"DNS           : {HOST} -> {', '.join(addrs)}")
    except Exception as error:  # noqa: BLE001
        print(f"DNS           : [FAIL] cannot resolve {HOST}: {scrub(error)}")
        print("=> failure is at: TCP CONNECTION (no internet/DNS)")
        return 1

    results = [test_starttls(), test_ssl()]
    configured = next(r for r in results if r.port == (465 if config.SMTP_USE_SSL else 587))
    other = next(r for r in results if r is not configured)

    print("\n=== SUMMARY ===")
    for r in results:
        print(f"  {r.name:<30} " + ("WORKS" if r.works else f"FAILS at {r.failed_at.upper()}"))

    if configured.works:
        print(f"\n  Your current setting (SMTP_PORT={configured.port}) works - no .env change needed.")
    elif other.works:
        print(f"\n  Your current setting (SMTP_PORT={configured.port}) fails, but port "
              f"{other.port} works. To use it, set in .env:   SMTP_PORT={other.port}")
    else:
        print("\n  Neither method works from this PC/network. See the FAIL lines above.")
        if all(r.failed_at in ("TCP connection", "STARTTLS/TLS") for r in results):
            print("  Typical causes: antivirus e-mail scanning, firewall, or the Wi-Fi/ISP/"
                  "college network blocking SMTP. Try once on a phone hotspot.")

    if send_to:
        method = configured if configured.works else (other if other.works else None)
        if method is None:
            print("\n  --send skipped: no method authenticated successfully.")
            return 1
        print(f"\n--- Sending ONE diagnostic email to {send_to} via port {method.port} ---")
        final = test_starttls(send_to) if method.port == 587 else test_ssl(send_to)
        if final.sent:
            print(f"\nRESULT: SENT via port {final.port} - check the Inbox and Spam of {send_to}")
        else:
            print(f"\nRESULT: FAILED at {(final.failed_at or 'sending').upper()}")
            return 1
        return 0 if configured.works else 1

    return 0 if configured.works else 1


if __name__ == "__main__":
    sys.exit(main())
