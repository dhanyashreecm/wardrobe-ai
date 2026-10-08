#!/bin/bash
# Double-click: runs the Virtual Try-On backend tests (no real AI calls).
cd "$(dirname "$0")"
./ai_env312/bin/python -m unittest -v backend.tests.test_virtual_tryon backend.tests.test_tryon_usage backend.tests.test_shopping_links 2>&1 | tee backups/_claude_tmp/tryon_backend_tests.log
echo; echo "Finished - you can close this window."
