#!/bin/bash

echo "Stopping existing uvicorn process..."
pkill -9 -f "uvicorn main:app" 2>/dev/null

echo "Waiting for port 8031 to be free..."
while fuser 8031/tcp > /dev/null 2>&1; do
    sleep 0.3
done

echo "Starting uvicorn..."
"$(dirname "$0")/venv/bin/uvicorn" main:app --host 0.0.0.0 --port 8031