#!/bin/bash

echo "Stopping existing uvicorn process..."
pkill -f "uvicorn main:app" 2>/dev/null
sleep 1

echo "Starting uvicorn..."
uvicorn main:app --host 0.0.0.0 --port 8031
