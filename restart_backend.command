#!/bin/bash
# Double-click me: stops the running backend and starts it again with the new settings.
cd "$(dirname "$0")"
PIDS=$(lsof -ti tcp:5001)
if [ -n "$PIDS" ]; then echo "Stopping the old backend..."; kill $PIDS; sleep 2; fi
echo "Starting the backend (keep this window open)..."
./ai_env312/bin/python -u -m backend.app 2>&1 | tee backups/_claude_tmp/backend_live.log
