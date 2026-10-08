#!/bin/bash
cd "$(dirname "$0")"
./ai_env312/bin/python -m scripts.vto_verify_db 2>&1 | tee scripts/vto_verify_db_output.txt
echo; read -p "Press Enter to close" _
