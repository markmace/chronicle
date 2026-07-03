"""Regenerates docs/screenshots/*.png against a local dev server.

Drives Chrome over the DevTools Protocol directly (via `websockets`, already
a transitive dependency through `mcp` -- no new package needed) instead of
relying on Chrome's --window-size CLI flag. On this machine's Chrome build,
--window-size is silently floored around 500px in headless screenshot mode:
request a narrower viewport and the page still *lays out* at ~500px wide,
then the output image is just cropped to the requested size -- producing
what looks like a desktop layout cropped into a mobile-shaped frame.
Emulation.setDeviceMetricsOverride sets the actual rendering viewport
directly and doesn't have that problem.

Usage: uv run python scripts/screenshot.py
Requires: .dev.env configured (see .dev.env.example), Google Chrome installed
at the standard macOS path below.
"""

import asyncio
import base64
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT = 9333
APP_PORT = 8098
ROOT = Path(__file__).parent.parent
OUT = ROOT / "docs" / "screenshots"

MOBILE = (390, 844)
DESKTOP = (1440, 900)


async def _send(ws, msg_id_box, method: str, params: dict | None = None) -> dict:
    msg_id_box[0] += 1
    this_id = msg_id_box[0]
    await ws.send(json.dumps({"id": this_id, "method": method, "params": params or {}}))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == this_id:
            return resp


async def capture(url: str, width: int, height: int, dark: bool, out_path: Path, scale: int = 2) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.put(f"http://localhost:{CDP_PORT}/json/new?about:blank")
        target = r.json()

    msg_id = [0]
    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=50 * 1024 * 1024) as ws:
        await _send(ws, msg_id, "Page.enable")
        await _send(ws, msg_id, "Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": scale, "mobile": width < 700,
        })
        if dark:
            await _send(ws, msg_id, "Emulation.setEmulatedMedia", {
                "features": [{"name": "prefers-color-scheme", "value": "dark"}],
            })
        await _send(ws, msg_id, "Page.navigate", {"url": url})

        while True:
            resp = json.loads(await ws.recv())
            if resp.get("method") == "Page.loadEventFired":
                break

        await _send(ws, msg_id, "Runtime.evaluate", {
            "expression": "document.fonts.ready.then(() => true)",
            "awaitPromise": True,
        })

        result = await _send(ws, msg_id, "Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
        })

    out_path.write_bytes(base64.b64decode(result["result"]["data"]))

    async with httpx.AsyncClient() as client:
        await client.get(f"http://localhost:{CDP_PORT}/json/close/{target['id']}")


async def main() -> None:
    if not Path(CHROME).exists():
        raise SystemExit(f"Google Chrome not found at {CHROME} — edit CHROME in this script.")

    OUT.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for line in (ROOT / ".dev.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    token = env["MCP_TOKEN"]

    app_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "main:app", "--port", str(APP_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    chrome_proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--remote-debugging-port={CDP_PORT}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        time.sleep(2)
        base = f"http://localhost:{APP_PORT}"

        await capture(f"{base}/view/{token}", *MOBILE, False, OUT / "list-view.png")
        await capture(f"{base}/view/{token}", *MOBILE, True, OUT / "list-view-dark.png")
        await capture(f"{base}/view/{token}", *DESKTOP, False, OUT / "list-view-desktop.png")
        await capture(f"{base}/login", *MOBILE, False, OUT / "login.png")

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base}/api/{token}/items")
            items = r.json()["items"]
        if items:
            await capture(f"{base}/view/{token}/{items[0]['id']}/edit", *MOBILE, False, OUT / "edit-screen.png")

        print(f"Wrote screenshots to {OUT}/")
    finally:
        chrome_proc.terminate()
        app_proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
