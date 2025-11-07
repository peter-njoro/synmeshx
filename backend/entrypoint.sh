#!/bin/bash
set -e

# Wait for Postgres
while ! nc -z "$POSTGRES_HOST" "$POSTGRES_PORT"; do
  echo "Waiting for PostgreSQL at $POSTGRES_HOST:$POSTGRES_PORT..."
  sleep 1
done

# Activate uv virtual environment if present
if [ -f ".venv/bin/activate" ]; then
  # shellcheck source=/dev/null
  . .venv/bin/activate
fi

# Run migrations: prefer venv's Python to avoid running a script with a broken shebang
if [ -x ".venv/bin/python" ]; then
  .venv/bin/python -m alembic upgrade head
else
  # fallback to whatever python is available in PATH
  python -m alembic upgrade head
fi

# Start app
uvicorn app.main:app --host 0.0.0.0 --port 8000
