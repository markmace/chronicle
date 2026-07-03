#!/usr/bin/env bash
# Regenerates docs/screenshots/*.png against a local dev server, so the README
# stays a true reflection of the current UI as it's iterated on.
#
# Usage: ./scripts/screenshot.sh
# Requires: .dev.env configured (see .dev.env.example), Google Chrome installed.

set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8098
OUT=docs/screenshots
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -f "$CHROME" ]; then
  echo "Google Chrome not found at the expected path — edit CHROME in this script." >&2
  exit 1
fi

mkdir -p "$OUT"

set -a
source .dev.env
set +a

uv run uvicorn main:app --port "$PORT" > /tmp/chronicle_screenshot_server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
sleep 2

COOKIES=$(mktemp)
curl -s -c "$COOKIES" -X POST "http://localhost:$PORT/login" \
  --data-urlencode "password=$VIEW_PASSWORD" -o /dev/null

shot() {
  # $1 = output name, $2 = path, $3 = extra chrome flags (optional)
  # --force-device-scale-factor=2 for crisp (Retina-equivalent) images —
  # otherwise these come out visibly soft on any modern display.
  "$CHROME" --headless=new --disable-gpu --no-sandbox --window-size=390,900 \
    --force-device-scale-factor=2 \
    ${3:-} --screenshot="$OUT/$1.png" "http://localhost:$PORT$2" 2>/dev/null
}

shot "list-view" "/view/$MCP_TOKEN"
shot "list-view-dark" "/view/$MCP_TOKEN" "--force-dark-mode --enable-features=WebUIDarkMode"
shot "login" "/login"

ITEM_ID=$(curl -s "http://localhost:$PORT/api/$MCP_TOKEN/items" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['items'][0]['id'] if d['items'] else '')")
if [ -n "$ITEM_ID" ]; then
  shot "edit-screen" "/view/$MCP_TOKEN/$ITEM_ID/edit"
fi

rm -f "$COOKIES"
echo "Wrote screenshots to $OUT/"
