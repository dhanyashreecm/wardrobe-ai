"""
Diagnoses "I'm not getting the reset / verification code".

    python -m backend.check_email someone@gmail.com
    python -m backend.check_email someone@gmail.com --send-code

1. checks an account exists for that exact email in the database
2. shows whether it is still waiting for email verification
3. sends ONE test email to it right now (not in the background) and
   prints whether Gmail accepted it, or why not.
4. with --send-code: also makes a fresh verification code for an
   unverified account and sends it right now, reporting the result.
"""
import re
import sys

from backend import config, email_service
from backend.db import users_collection


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    send_code = "--send-code" in sys.argv
    if len(args) != 1:
        print("Usage: python -m backend.check_email someone@gmail.com [--send-code]")
        return

    email = args[0].strip().lower()
    print(f"Sender Gmail configured : {config.email_configured()}")
    print(f"Sending as              : {config.SMTP_USERNAME or '(SMTP_USERNAME not set)'}")
    print(f"SMTP server             : {config.SMTP_HOST}:{config.SMTP_PORT}")
    print(f"Verification required   : {config.REQUIRE_EMAIL_VERIFICATION}")

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
            print("CODE: not needed - this account is already verified, just log in.")
        elif result["status"] == "too_soon":
            print("CODE: a code was sent less than a minute ago - wait 60s and re-run.")
        elif result["status"] == "ok":
            ok, why = email_service.send_email(
                email, f"Your Wardrobe-AI verification code: {result['code']}",
                f"Your Wardrobe-AI verification code is {result['code']}.\n"
                f"It expires in {VERIFY_CODE_MINUTES} minutes.\n")
            print("CODE: " + ("new code SENT - check inbox and Spam" if ok else "FAILED - " + why))


if __name__ == "__main__":
    main()
