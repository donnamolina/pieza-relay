#!/usr/bin/env python3
"""
7zap relay server — runs on Mac mini where cf_clearance cookie is valid.
Proxies 7zap API calls from the DigitalOcean parts-bot server.

Install: pip install fastapi uvicorn httpx
Run:     python3 7zap_relay_server.py
PM2:     pm2 start 7zap_relay_server.py --name 7zap-relay --interpreter python3
"""

import os
import logging
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

# Load .env from same directory
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("7zap-relay")

RELAY_TOKEN  = os.getenv("RELAY_TOKEN", "")
SESSION_VAL  = os.getenv("SEVENZAP_COOKIE_SESSION", "")
REMEMBER_RAW = os.getenv("SEVENZAP_COOKIE_REMEMBER", "")
CF_VAL       = os.getenv("SEVENZAP_COOKIE_CF", "")
UA           = os.getenv("SEVENZAP_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

# Build cookie dict
_cookies: dict[str, str] = {}
if SESSION_VAL:
    _cookies["7zap"] = SESSION_VAL
if CF_VAL:
    _cookies["cf_clearance"] = CF_VAL
if REMEMBER_RAW:
    if REMEMBER_RAW.startswith("remember_web_") and "=" in REMEMBER_RAW:
        name, _, val = REMEMBER_RAW.partition("=")
        _cookies[name.strip()] = val.strip()
    else:
        _cookies["remember_web"] = REMEMBER_RAW

COOKIE_HEADER = "; ".join(f"{k}={v}" for k, v in _cookies.items())
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://7zap.com/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "Cookie": COOKIE_HEADER,
}

ALLOWED_HOST = "7zap.com"

app = FastAPI(title="7zap Relay", docs_url=None, redoc_url=None)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "cookies_configured": bool(SESSION_VAL and CF_VAL),
        "token_set": bool(RELAY_TOKEN),
    }


@app.get("/proxy")
async def proxy(request: Request):
    token = request.headers.get("x-relay-token", "")
    if RELAY_TOKEN and token != RELAY_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    target_url = request.query_params.get("_url", "")
    if not target_url:
        raise HTTPException(status_code=400, detail="Missing _url param")
    if ALLOWED_HOST not in target_url:
        raise HTTPException(status_code=400, detail=f"Only {ALLOWED_HOST} URLs allowed")

    params = {k: v for k, v in request.query_params.items() if k != "_url"}
    logger.info(f"→ {target_url}  params={params}")

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(target_url, params=params, headers=HEADERS)

        if resp.status_code in (401, 403):
            logger.error(f"7zap returned {resp.status_code} — cf_clearance likely expired")
            return JSONResponse(
                {"error": f"cf_clearance expired (HTTP {resp.status_code})"},
                status_code=resp.status_code,
            )

        try:
            return JSONResponse(resp.json(), status_code=resp.status_code)
        except Exception:
            return JSONResponse(
                {"error": "non-JSON response from 7zap", "body": resp.text[:500]},
                status_code=502,
            )

    except Exception as e:
        logger.error(f"Relay request failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("RELAY_PORT", "8765"))
    logger.info(f"7zap relay starting on port {port}")
    logger.info(f"Auth token: {'set' if RELAY_TOKEN else 'NONE (open!)'}")
    logger.info(f"Cookies: 7zap={bool(SESSION_VAL)}, cf={bool(CF_VAL)}, remember={bool(REMEMBER_RAW)}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
