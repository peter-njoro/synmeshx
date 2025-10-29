#!/bin/sh
uv sync
until pg_isready -h db -p 5432 -U postgres; do sleep 1; done
alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
