"""
Send the "Welcome to Wardrobe AI" email to an existing account, now.

    python3 -m backend.send_welcome_now someone@gmail.com

Uses the same email settings as the app (.env). Waits for the send to
finish and prints whether Gmail accepted it.
"""
import logging
import sys

from backend import config, email_service

logging.basicConfig(level=logging.INFO, format="%(message)s")


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 -m backend.send_welcome_now someone@gmail.com")
        sys.exit(1)

    address = sys.argv[1].strip().lower()

    if not config.email_configured():
        print("Email is not set up: SMTP_USERNAME / SMTP_PASSWORD missing in .env")
        sys.exit(1)

    name = None
    try:
        from backend.auth import find_user_by_email
        user = find_user_by_email(address) or {}
        name = user.get("name")
    except Exception:
        pass  # no name found - the email just says "Hi there"

    thread = email_service.send_welcome_email(name, address)
    if thread is not None:
        thread.join()
    print("Done - see the 'Email sending ...' line above for the result.")


if __name__ == "__main__":
    main()
