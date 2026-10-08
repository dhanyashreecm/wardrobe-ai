#!/bin/bash
# Double-click to start the Wardrobe-AI backend (http://localhost:5001).
cd "$(dirname "$0")"
./ai_env312/bin/python -m backend.app
