#!/bin/bash
# Double-click to start the Wardrobe-AI backend (http://localhost:5001).
# Output is also saved to backups/_claude_tmp/backend_live.log so problems can be diagnosed.
cd "$(dirname "$0")"
mkdir -p backups/_claude_tmp
./ai_env312/bin/python -u -m backend.app 2>&1 | tee backups/_claude_tmp/backend_live.log
