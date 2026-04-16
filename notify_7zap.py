#!/usr/bin/env python3
"""
notify_7zap.py — sends an email alert when 7zap cookies expire.
Called by:
  - sync_ngrok_url.sh  (3 consecutive health-check failures)
  - refresh_cookies.py (session cookie missing / auth error)

Credentials loaded from ~/.pieza-relay/.env:
  NOTIFY_EMAIL_FROM=your-gmail@gmail.com
  NOTIFY_EMAIL_PASS=xxxx xxxx xxxx xxxx   ← Gmail App Password (16 chars, no spaces optional)
  NOTIFY_EMAIL_TO=matthewdolofan8@gmail.com
"""

import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

RELAY_DIR  = Path(__file__).parent
FLAG_FILE  = RELAY_DIR / ".notified"
ENV_FILE   = RELAY_DIR / ".env"

# ── Load .env ───────────────────────────────────────────────────────────────
_env: dict[str, str] = {}
if ENV_FILE.exists():
    for _line in ENV_FILE.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            _env[_k.strip()] = _v.strip()

FROM_ADDR = _env.get("NOTIFY_EMAIL_FROM", "")
FROM_PASS = _env.get("NOTIFY_EMAIL_PASS", "")
TO_ADDR   = _env.get("NOTIFY_EMAIL_TO", "matthewdolofan8@gmail.com")

SUBJECT = "7zap cookies expired — action needed"

_BODY_TEMPLATE = """\
The 7zap relay on the Mac mini has failed to reach 7zap.com.
The Cloudflare session cookie (cf_clearance) is likely expired.

━━ HOW TO FIX ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. Open Google Chrome on the Mac mini.
  2. Go to https://7zap.com and log in if prompted.
  3. Quit Chrome completely (Cmd+Q — full quit, not just close window).
  4. Open Terminal and run:
       python3 ~/pieza-relay/refresh_cookies.py
  5. That's it. The relay will restart automatically.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Detection time : {ts}
Mac mini relay : http://localhost:8765
"""


# ── Public helpers ───────────────────────────────────────────────────────────

def already_notified() -> bool:
    """Return True if a notification was already sent for this failure event."""
    return FLAG_FILE.exists()


def set_notified():
    """Mark that a notification has been sent (prevents spam)."""
    FLAG_FILE.touch()


def clear_notified():
    """Clear the flag — call this after cookies are successfully refreshed."""
    FLAG_FILE.unlink(missing_ok=True)


def send_email(reason: str = "") -> bool:
    """Send the alert email. Returns True on success."""
    if not FROM_ADDR or not FROM_PASS:
        print(
            "notify_7zap: NOTIFY_EMAIL_FROM / NOTIFY_EMAIL_PASS not set in .env — "
            "cannot send email",
            file=sys.stderr,
        )
        return False

    body = _BODY_TEMPLATE.format(ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if reason:
        body += f"\nTrigger reason : {reason}\n"

    msg = MIMEText(body)
    msg["Subject"] = SUBJECT
    msg["From"]    = FROM_ADDR
    msg["To"]      = TO_ADDR

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(FROM_ADDR, FROM_PASS)
            smtp.send_message(msg)
        print(f"notify_7zap: alert sent to {TO_ADDR}")
        return True
    except Exception as exc:
        print(f"notify_7zap: failed to send email — {exc}", file=sys.stderr)
        return False


def notify(reason: str = ""):
    """Send notification once per failure event (guarded by FLAG_FILE)."""
    if already_notified():
        print(
            "notify_7zap: already notified — skipping. "
            "Delete ~/pieza-relay/.notified to re-enable."
        )
        return
    if send_email(reason):
        set_notified()


# ── CLI entry-point (called from bash scripts) ───────────────────────────────
if __name__ == "__main__":
    reason = " ".join(sys.argv[1:])
    notify(reason=reason)
