#!/bin/bash
set -e

# Wait for Postgres
while ! nc -z "$POSTGRES_HOST" "$POSTGRES_PORT"; do
  echo "Waiting for PostgreSQL at $POSTGRES_HOST:$POSTGRES_PORT..."
  sleep 1
done

# Activate uv virtual environment
source .venv/bin/activate

# Run migrations
alembic upgrade head

# Start app
uvicorn app.main:app --host 0.0.0.0 --port 8000
