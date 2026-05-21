#!/bin/sh
# Startup script for Railway deployment
# Properly expands PORT environment variable

PORT=${PORT:-8000}
exec uvicorn backend.main:app --host 0.0.0.0 --port $PORT
