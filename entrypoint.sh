#!/bin/sh
# entrypoint.sh
# This script reads environment variables and launches Waitress with them.

# Exit immediately if a command exits with a non-zero status.
set -e

# Use environment variables for Waitress settings, providing defaults if they are not set.
HOST="${WAITRESS_HOST:-0.0.0.0}"
PORT="${WAITRESS_PORT:-5000}"
THREADS="${WAITRESS_THREADS:-4}"

echo "Starting Waitress server on host ${HOST}, port ${PORT} with ${THREADS} threads..."

# Execute waitress-serve using the variables
# 'exec' replaces the shell process with the waitress process
exec waitress-serve \
     --host="${HOST}" \
     --port="${PORT}" \
     --threads="${THREADS}" \
     app:app
