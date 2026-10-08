#!/bin/bash
# Double-click: checks the "same item = 100%" rule on your wardrobe photos.
cd "$(dirname "$0")"
./ai_env312/bin/python -m scripts.calibrate_same_item
echo; echo "Finished - you can close this window."
