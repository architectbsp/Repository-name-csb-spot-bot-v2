#!/bin/bash
# Double-clickable macOS launcher for the CSB Spot Bot desktop app.
#
# Finder runs .command files in a new Terminal window when you
# double-click them. This script activates the project's virtual
# environment (creating it on first run if missing) and starts the bot
# as a native desktop window (Flet + flet-desktop -- not a browser tab).
#
# First-time setup: make this file double-clickable once with:
#   chmod +x run_bot.command
# Then just double-click run_bot.command from Finder any time you want
# to launch the bot.

set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "No virtual environment found -- creating one in .venv ..."
    python3 -m venv .venv
    ".venv/bin/pip" install --upgrade pip
    ".venv/bin/pip" install -r requirements.txt
fi

echo "Starting CSB Spot Bot..."
".venv/bin/python" main.py

echo
echo "Bot process exited. Press Enter to close this window."
read -r _
