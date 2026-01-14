#!/usr/bin/env bash
set -euo pipefail

# Build and run docker-compose for quick testing
docker compose build
docker compose up --detach

echo "Containers started. Use 'docker compose logs -f' to follow logs."