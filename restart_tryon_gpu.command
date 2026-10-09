#!/bin/bash
# Double-click: restarts the Kaggle try-on GPU with the latest notebook
# (spaces/tryon/kaggle_kernel/wardrobe_tryon_kernel.py), then restarts
# the backend so it uses the new GPU address.
cd "$(dirname "$0")"
LOG=backups/_claude_tmp/tryon_gpu.log
mkdir -p backups/_claude_tmp
{
echo "== $(date) making sure the kaggle tool is installed"
./ai_env312/bin/python -m pip install -q kaggle
echo "== $(date) stopping old GPU session"
./ai_env312/bin/python -m backend.kaggle_tryon stop
echo "== starting new GPU session (can take 5-20 minutes)"
if ./ai_env312/bin/python -m backend.kaggle_tryon start --hours 4; then
  echo "== GPU ready - restarting backend"
  lsof -ti tcp:5001 | xargs kill 2>/dev/null
  sleep 3
  open start_backend.command
  echo "GPU RESTART OK"
else
  echo "GPU RESTART FAILED"
fi
} 2>&1 | tee "$LOG"
echo; echo "Finished - you can close this window."
