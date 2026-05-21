#!/bin/sh
# Startup script for Railway deployment
# Run on fixed port 8000

exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
