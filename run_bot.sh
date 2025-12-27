#!/bin/bash
# Script to run the bot with proper library paths

# Set library path for Opus on macOS
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH

# Activate virtual environment and run bot
cd "$(dirname "$0")"
source venv/bin/activate
python bot.py

