#!/usr/bin/env bash
set -euo pipefail

# Quick local runner for development/testing
# Usage: ./run_local.sh
# Requires BOT_TOKEN and ADMIN_IDS in .env or in environment variables

# Load .env if present
if [ -f .env ]; then
  # shellcheck disable=SC1091
  export $(grep -v '^#' .env | xargs) || true
fi

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "ERROR: BOT_TOKEN not set. Copy .env.example -> .env and set BOT_TOKEN."
  exit 1
fi

# create venv and install deps if needed
if [ ! -d .venv ]; then
  python -m venv .venv
fi
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Run the bot
exec python src/bot.py
