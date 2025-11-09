#!/bin/bash
set -e

# Wait for Postgres
while ! nc -z "$POSTGRES_HOST" "$POSTGRES_PORT"; do
  echo "Waiting for PostgreSQL at $POSTGRES_HOST:$POSTGRES_PORT..."
  sleep 1
done

# Run Alembic migrations
cd /app || exit 1
python -c "from alembic import command; from alembic.config import Config; command.upgrade(Config('alembic.ini'), 'head')"

# Start the app
uvicorn app.main:app --host 0.0.0.0 --port 8000
