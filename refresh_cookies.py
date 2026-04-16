#!/usr/bin/env python3
"""
refresh_cookies.py — reads 7zap cookies from Chrome on this Mac mini,
updates ~/pieza-relay/.env, and restarts the 7zap-relay PM2 process.
Runs every 2 hours via com.pieza.refresh-cookies LaunchAgent.

Requires: pip3 install pycookiecheat
Note: Chrome must be closed (or at least 7zap.com cookies must be flushed to disk).
      On macOS, Chrome flushes cookies periodically even while running.
"""

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"
LOG_FILE = Path("/tmp/refresh_cookies.log")

# Notification helper (same directory)
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("notify_7zap", Path(__file__).parent / "notify_7zap.py")
    _notify_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_notify_mod)
    _notify      = _notify_mod.notify
    _clear_notified = _notify_mod.clear_notified
except Exception as _e:
    def _notify(reason: str = ""): pass        # no-op if module missing
    def _clear_notified(): pass


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}: {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def set_env_var(text: str, key: str, value: str) -> str:
    """Replace key=... line in .env text, or append if missing."""
    pattern = rf'^{re.escape(key)}=.*$'
    replacement = f'{key}={value}'
    if re.search(pattern, text, re.MULTILINE):
        return re.sub(pattern, replacement, text, flags=re.MULTILINE)
    return text.rstrip('\n') + f'\n{key}={value}\n'


def main():
    log("=== refresh_cookies.py starting ===")

    # ── 1. Import pycookiecheat ───────────────────────────────────────────
    try:
        from pycookiecheat import BrowserType, chrome_cookies
    except ImportError:
        log("ERROR: pycookiecheat not installed. Run: pip3 install pycookiecheat")
        sys.exit(1)

    # ── 2. Read Chrome cookies for 7zap.com ──────────────────────────────
    # Find whichever Chrome profile has 7zap.com cookies
    import sqlite3, shutil, tempfile
    chrome_base = Path.home() / "Library/Application Support/Google/Chrome"
    best_profile = None
    for profile in ["Profile 1", "Default", "Profile 2", "Profile 3"]:
        db = chrome_base / profile / "Cookies"
        if not db.exists():
            continue
        try:
            tmp = Path(tempfile.mktemp(suffix=".db"))
            shutil.copy2(db, tmp)
            conn = sqlite3.connect(tmp)
            count = conn.execute("SELECT COUNT(*) FROM cookies WHERE host_key LIKE '%7zap%'").fetchone()[0]
            conn.close()
            tmp.unlink()
            if count > 0:
                best_profile = db
                log(f"Found {count} 7zap cookies in {profile}")
                break
        except Exception:
            continue

    if not best_profile:
        log("ERROR: no 7zap cookies in any Chrome profile — visit 7zap.com in Chrome first")
        sys.exit(1)

    log(f"Reading Chrome cookies for 7zap.com from {best_profile.parent.name}...")
    try:
        cookies: dict = chrome_cookies("https://7zap.com", browser=BrowserType.CHROME,
                                       cookie_file=str(best_profile))
    except Exception as e:
        log(f"ERROR reading Chrome cookies: {e}")
        log("Tip: try closing Chrome first, or ensure 7zap.com has been visited recently")
        sys.exit(1)

    if not cookies:
        log("ERROR: no cookies returned for 7zap.com — visit 7zap.com in Chrome first")
        sys.exit(1)

    log(f"Raw cookie keys found: {list(cookies.keys())}")

    # ── 3. Extract required cookies ──────────────────────────────────────
    session = cookies.get("7zap", "")
    cf      = cookies.get("cf_clearance", "")

    # remember_web has a dynamic hash suffix: remember_web_<hash>=<token>
    remember_key = next((k for k in cookies if k.startswith("remember_web_")), None)
    if remember_key:
        remember = f"{remember_key}={cookies[remember_key]}"
    else:
        remember = ""

    log(f"7zap session  : {'found (' + session[:12] + '...)' if session else 'MISSING'}")
    log(f"cf_clearance  : {'found (' + cf[:12] + '...)' if cf else 'MISSING'}")
    log(f"remember_web  : {'found (' + remember_key + ')' if remember_key else 'MISSING'}")

    if not session:
        log("ERROR: 7zap session cookie missing — log in to 7zap.com in Chrome and retry")
        _notify(reason="7zap session cookie missing from Chrome — please log in")
        sys.exit(1)

    if not cf:
        log("WARNING: cf_clearance missing — requests may fail Cloudflare challenge")

    # ── 4. Read and update .env ───────────────────────────────────────────
    if not ENV_FILE.exists():
        log(f"ERROR: .env not found at {ENV_FILE}")
        sys.exit(1)

    env_text = ENV_FILE.read_text()
    changed = False

    old_session = re.search(r'^SEVENZAP_COOKIE_SESSION=(.*)$', env_text, re.MULTILINE)
    if not old_session or old_session.group(1) != session:
        env_text = set_env_var(env_text, "SEVENZAP_COOKIE_SESSION", session)
        changed = True
        log("Updated SEVENZAP_COOKIE_SESSION")

    if cf:
        old_cf = re.search(r'^SEVENZAP_COOKIE_CF=(.*)$', env_text, re.MULTILINE)
        if not old_cf or old_cf.group(1) != cf:
            env_text = set_env_var(env_text, "SEVENZAP_COOKIE_CF", cf)
            changed = True
            log("Updated SEVENZAP_COOKIE_CF")

    if remember:
        old_rem = re.search(r'^SEVENZAP_COOKIE_REMEMBER=(.*)$', env_text, re.MULTILINE)
        if not old_rem or old_rem.group(1) != remember:
            env_text = set_env_var(env_text, "SEVENZAP_COOKIE_REMEMBER", remember)
            changed = True
            log("Updated SEVENZAP_COOKIE_REMEMBER")

    if not changed:
        log("All cookies unchanged — no restart needed")
        return

    ENV_FILE.write_text(env_text)
    log(f"Saved updated .env to {ENV_FILE}")

    # ── 5. Restart 7zap-relay ─────────────────────────────────────────────
    log("Restarting 7zap-relay via PM2...")
    result = subprocess.run(
        ["/opt/homebrew/bin/pm2", "restart", "7zap-relay"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log("PM2: 7zap-relay restarted successfully")
        # Cookies refreshed OK — clear any pending failure notification
        _clear_notified()
        log("Cleared .notified flag (if set)")
    else:
        log(f"PM2 restart failed (exit {result.returncode}): {result.stderr.strip()}")
        sys.exit(1)

    log("=== Done ===")


if __name__ == "__main__":
    main()
