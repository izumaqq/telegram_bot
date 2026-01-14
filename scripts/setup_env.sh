#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  echo ".env already exists, leaving it untouched."
  exit 0
fi

cp .env.example .env
chmod 600 .env
cat .env

echo "Created .env from .env.example. Edit .env to add BOT_TOKEN and ADMIN_IDS before running."