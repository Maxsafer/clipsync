#!/bin/bash
cd "$(dirname "$0")"

PORT=""
if [ -f .env ]; then
  PORT=$(grep -E '^CLIPSYNC_PORT=' .env | head -1 | cut -d= -f2-)
  PORT="${PORT//\"/}"
  PORT="${PORT//\'/}"
  PORT="${PORT// /}"
fi
PORT="${PORT:-8080}"

IFACE="$(route get 8.8.8.8 2>/dev/null | awk '/interface:/{print $2}')"
IP="$(ipconfig getifaddr "$IFACE")"

URL="http://${IP}:${PORT}"
echo "Opening ${URL}"
open "${URL}"
