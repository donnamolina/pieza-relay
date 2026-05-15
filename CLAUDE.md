# CLAUDE.md — pieza-relay

> Repo-specific context for Claude Code sessions. Cross-project info lives in [molina-vault](https://github.com/donnamolina/molina-vault).

## What this is
Python FastAPI residential-IP relay for 7zap catalog lookups. Runs on the Mac mini because `cf_clearance` is IP-locked to whatever IP passed Cloudflare's challenge. Called by `parts-bot` on Droplet B.

## Stack
- Python + FastAPI + uvicorn

## Conventions
- Port: 8765, binds `0.0.0.0` (publicly reachable via Cloudflare Tunnel)
- LaunchD agent: `com.pieza.7zap-relay`
- Cookie refresh agents: `com.pieza.refresh-cookies`, `com.pieza.refresh-partsouq-cookies` — check if running before assuming cookie freshness

## Deployment
Mac mini (Donna), LaunchD. Not on a droplet — must stay on residential IP.

## Don't
- Don't move this off the Mac mini without solving the residential-IP problem
- Don't change port 8765 without also updating `parts-bot` config
- Don't deploy to a datacenter IP — Cloudflare will challenge and `cf_clearance` won't work

## More context
- Vault: `projects/parts-bot.md` in `donnamolina/molina-vault`
- Infrastructure: `infra/mac-mini-donna.md`
