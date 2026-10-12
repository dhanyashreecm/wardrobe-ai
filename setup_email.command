#!/bin/bash
# Double-click me: saves the Gmail App Password and sends the welcome email.
cd "$(dirname "$0")"
if [ -x ./ai_env312/bin/python ]; then PY=./ai_env312/bin/python; else PY=python3; fi
echo "Paste the 16-letter Gmail App Password for dhanyashree616@gmail.com and press Enter."
echo "(Nothing will show while you paste - that's normal.)"
echo
$PY -m backend.set_secret SMTP_PASSWORD || { echo "Saving failed."; read -p "Press Enter to close"; exit 1; }
echo
echo "Sending the welcome email to vrishabkempula25@gmail.com ..."
$PY -m backend.send_welcome_now vrishabkempula25@gmail.com
echo
read -p "Done. Press Enter to close this window."
