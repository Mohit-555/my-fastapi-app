#!/bin/bash
set -e

echo "Creating tables and seeding database..."
python seed.py

echo "Stamping Alembic database migration version..."
alembic stamp head

echo "Starting FastAPI application with Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
