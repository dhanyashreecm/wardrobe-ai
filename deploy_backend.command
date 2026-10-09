#!/bin/bash
# Double-click: deploys the backend to your free Hugging Face Space so the
# phone app has a permanent https server. Asks for your HF token (hidden).
cd "$(dirname "$0")"
mkdir -p backups/_claude_tmp
./ai_env312/bin/python -m pip install -q huggingface_hub
./ai_env312/bin/python -m scripts.deploy_hf_space 2>&1 | tee backups/_claude_tmp/deploy.log
echo; echo "Finished - you can close this window."
