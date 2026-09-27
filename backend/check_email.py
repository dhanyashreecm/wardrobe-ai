"""
Diagnoses "I'm not getting the reset code".

    python -m backend.check_email someone@gmail.com

1. checks an account exists for that exact email in the database
2. sends ONE test email to it right now (not in the background) and
   prints whether Gmail accepted it, or why not.
"""
import re
import sys

from backend import config, email_service
from backend.db import users_collection


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m backend.check_email someone@gmail.com")
        return

    email = sys.argv[1].strip()
    print(f"Sender Gmail configured : {config.email_configured()}")
    print(f"SMTP server             : {config.SMTP_HOST}:{config.SMTP_PORT}")

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

    print("Sending a test email now...")
    sent, detail = email_service.send_email(
        email,
        "Wardrobe AI test email",
        "If you can read this, Wardrobe AI can send you reset codes.\n",
    )
    print("RESULT: " + ("SENT - check the inbox and Spam of " + email if sent
                        else "FAILED - " + detail))


if __name__ == "__main__":
    main()
