"""
Diagnoses "I'm not getting the reset / verification code".

    python -m backend.check_email someone@gmail.com
    python -m backend.check_email someone@gmail.com --send-code
    python -m backend.check_email someone@gmail.com --send-reset

1. checks an account exists for that exact email in the database
2. shows whether it is still waiting for email verification
3. sends ONE test email to it right now (not in the background) and
   prints whether Gmail accepted it, or why not.
4. with --send-code: also makes a fresh verification code for an
   unverified account and sends it right now, reporting the result.
5. with --send-reset: makes a real password-reset code for the account
   and sends the real reset email right now (not in the background),
   reporting exactly what Gmail said. The code itself is NOT printed -
   read it from the inbox, then use it in the app.
"""
import re
import sys

from backend import config, email_service
from backend.db import users_collection


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    send_code = "--send-code" in sys.argv
    send_reset = "--send-reset" in sys.argv
    if len(args) != 1:
        print("Usage: python -m backend.check_email someone@gmail.com "
              "[--send-code] [--send-reset]")
        return

    email = args[0].strip().lower()
    print(f"Sender Gmail configured : {config.email_configured()}")
    print(f"Sending as              : {config.SMTP_USERNAME or '(SMTP_USERNAME not set)'}")
    print(f"SMTP server             : {config.SMTP_HOST}:{config.SMTP_PORT}")
    print(f"Verification required   : {config.REQUIRE_EMAIL_VERIFICATION}")
    pw = config.SMTP_PASSWORD or ""
    if "gmail" in config.SMTP_HOST.lower():
        looks_ok = len(pw) == 16 and pw.isalpha()
        print(f"App Password format     : {'OK (16 letters)' if looks_ok else 'UNEXPECTED - a Gmail App Password is 16 letters'}")

    exact = users_collection.find_one({"email": email})
    if exact:
        print(f"Account for {email}  : FOUND")
    else:
        similar = users_collection.find_one(
            {"email": {"$regex": f"^\\s*{re.escape(email)}\\s*$", "$options": "i"}}
        )
        if similar:
            print(f"Account for {email}  : NOT an exact match - stored as "
                  f"'{similar['email']}' (type it exactly like that)")
        else:
            print(f"Account for {email}  : NOT FOUND - no code is ever sent "
                  "to an email without an account")

    account = exact or users_collection.find_one(
        {"email": {"$regex": f"^\\s*{re.escape(email)}\\s*$", "$options": "i"}})
    if account:
        from backend.auth import is_email_verified
        verified = is_email_verified(account)
        print(f"Email verified          : {verified}")
        if not verified:
            print(f"Last code requested at  : {account.get('verify_requested_at')} (UTC)")
            print(f"Code expires at         : {account.get('verify_expires_at')} (UTC)")
            print(f"Wrong attempts so far   : {account.get('verify_attempts', 0)}")

    print("Sending a test email now...")
    sent, detail = email_service.send_email(
        email,
        "Wardrobe AI test email",
        "If you can read this, Wardrobe AI can send you reset codes.\n",
    )
    print("RESULT: " + ("SENT - check the inbox and Spam of " + email if sent
                        else "FAILED - " + detail))

    if send_code and account:
        from backend.auth import create_email_verification_code, VERIFY_CODE_MINUTES
        result = create_email_verification_code(email)
        if result["status"] == "already_verified":
            # A verified account never needs a verification code - the code
            # it gets from "Forgot Password" is a RESET code, so test that.
            print("CODE: account already verified - no verification code needed. "
                  "Testing the Forgot Password RESET code instead:")
            send_reset = True
        elif result["status"] == "too_soon":
            print("CODE: a code was sent less than a minute ago - wait 60s and re-run.")
        elif result["status"] == "ok":
            ok, why = email_service.send_email(
                email, f"Your Wardrobe-AI verification code: {result['code']}",
                f"Your Wardrobe-AI verification code is {result['code']}.\n"
                f"It expires in {VERIFY_CODE_MINUTES} minutes.\n")
            print("CODE: " + ("new code SENT - check inbox and Spam" if ok else "FAILED - " + why))

    if send_reset:
        # Exactly what POST /api/password/forgot does (same function).
        from backend.auth_routes import deliver_password_reset
        outcome = deliver_password_reset(email)
        status = outcome["status"]
        if status == "no_account":
            print("RESET: no account - the app sends nothing (correct behaviour).")
        elif status == "too_soon":
            print("RESET: a reset code was sent less than a minute ago (still valid) - "
                  "wait 60s and re-run to send a new one.")
        elif status == "sent":
            print(f"RESET: recipient = {outcome['recipient']}")
            print("RESET: reset email SENT - check inbox and Spam of " + outcome["recipient"])
        else:
            print(f"RESET: recipient = {outcome['recipient']}")
            print("RESET: FAILED - " + outcome["detail"] + " (the app would now show "
                  "'We couldn't send the reset email right now')")

if __name__ == "__main__":
    main()
