#!/bin/bash
set -e

echo "Creating tables and seeding database..."
python seed.py

echo "Running database migrations..."
alembic upgrade head

echo "Starting FastAPI application with Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
