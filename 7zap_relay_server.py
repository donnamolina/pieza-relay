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

# ── PartSouq cookies (separate from 7zap) ────────────────────────────────────
PSQ_CF_VAL    = os.getenv("PARTSOUQ_COOKIE_CF", "")
PSQ_PHPSESSID = os.getenv("PARTSOUQ_COOKIE_PHPSESSID", "")
PSQ_CSRF      = os.getenv("PARTSOUQ_COOKIE_CSRF", "")
PSQ_UA        = os.getenv("PARTSOUQ_USER_AGENT", UA)

_psq_cookies: dict[str, str] = {}
if PSQ_CF_VAL:
    _psq_cookies["cf_clearance"] = PSQ_CF_VAL
if PSQ_PHPSESSID:
    _psq_cookies["PHPSESSID"] = PSQ_PHPSESSID
if PSQ_CSRF:
    _psq_cookies["YII_CSRF_TOKEN"] = PSQ_CSRF

PSQ_COOKIE_HEADER = "; ".join(f"{k}={v}" for k, v in _psq_cookies.items())
PSQ_HEADERS = {
    "User-Agent": PSQ_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://partsouq.com/en/",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "Cookie": PSQ_COOKIE_HEADER,
}

PSQ_ALLOWED_HOST = "partsouq.com"

app = FastAPI(title="Pieza Relay (7zap + PartSouq)", docs_url=None, redoc_url=None)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "sevenzap": {
            "cookies_configured": bool(SESSION_VAL and CF_VAL),
        },
        "partsouq": {
            "cookies_configured": bool(PSQ_CF_VAL and PSQ_PHPSESSID),
            "cookie_names": list(_psq_cookies.keys()),
        },
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


@app.get("/partsouq/proxy")
async def partsouq_proxy(request: Request):
    """PartSouq catalog proxy — uses separate PartSouq cookies."""
    token = request.headers.get("x-relay-token", "")
    if RELAY_TOKEN and token != RELAY_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    target_url = request.query_params.get("_url", "")
    if not target_url:
        raise HTTPException(status_code=400, detail="Missing _url param")
    if PSQ_ALLOWED_HOST not in target_url:
        raise HTTPException(status_code=400, detail=f"Only {PSQ_ALLOWED_HOST} URLs allowed")

    params = {k: v for k, v in request.query_params.items() if k != "_url"}
    logger.info(f"[PartSouq] → {target_url}  params={list(params.keys())}")

    # Reload cookies fresh on each request (in case .env was updated by refresh script)
    _live_cf    = os.getenv("PARTSOUQ_COOKIE_CF", "")
    _live_php   = os.getenv("PARTSOUQ_COOKIE_PHPSESSID", "")
    _live_csrf  = os.getenv("PARTSOUQ_COOKIE_CSRF", "")
    _live_cookies = {}
    if _live_cf:
        _live_cookies["cf_clearance"] = _live_cf
    if _live_php:
        _live_cookies["PHPSESSID"] = _live_php
    if _live_csrf:
        _live_cookies["YII_CSRF_TOKEN"] = _live_csrf
    _live_cookie_header = "; ".join(f"{k}={v}" for k, v in _live_cookies.items())
    _live_headers = dict(PSQ_HEADERS)
    _live_headers["Cookie"] = _live_cookie_header

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=_live_headers,
        ) as client:
            resp = await client.get(target_url, params=params)

        if resp.status_code in (401, 403):
            logger.error(f"[PartSouq] {resp.status_code} — cf_clearance likely expired")
            return JSONResponse(
                {"error": f"cf_clearance expired (HTTP {resp.status_code})", "body": resp.text[:300]},
                status_code=resp.status_code,
            )

        from fastapi.responses import Response as FResponse
        return FResponse(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "text/html"),
            headers={"X-Final-URL": str(resp.url)},
        )

    except Exception as e:
        logger.error(f"[PartSouq] Relay request failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("RELAY_PORT", "8765"))
    logger.info(f"Pieza relay (7zap + PartSouq) starting on port {port}")
    logger.info(f"Auth token: {'set' if RELAY_TOKEN else 'NONE (open!)'}")
    logger.info(f"7zap cookies: session={bool(SESSION_VAL)}, cf={bool(CF_VAL)}, remember={bool(REMEMBER_RAW)}")
    logger.info(f"PartSouq cookies: cf={bool(PSQ_CF_VAL)}, phpsessid={bool(PSQ_PHPSESSID)}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
