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

> Note: This is parts-bot infrastructure, so the auto-log writes to `projects/parts-bot.md` in the vault, not a separate page.

## Auto-log substantive work to the vault

When you complete any substantive work in this repo — a deploy, a bug fix, a meaningful refactor, a schema change, a new feature shipped — append a one-line entry to the corresponding vault page's History section and commit the vault.

**Trigger:** substantive = anything you'd mention to a teammate at standup. Not: typo fixes, comment edits, dependency bumps, formatting-only changes.

**Where:** `~/molina-vault/projects/parts-bot.md` — find the `## History` section and add a line at the top of its list.

**Format:** `- YYYY-MM-DD: <one-line summary of what changed and why it matters>`

**Commit:** `cd ~/molina-vault && git add projects/parts-bot.md && git commit -m "auto: pieza-relay — <summary>"`

**Don't push the vault** unless I explicitly ask. Local commits are fine; pushing is my call.

**If the vault page doesn't exist** (new project, etc.), stop and ask me before creating one — vault structure is intentional.

**If you're unsure whether something counts as substantive**, ask. Better to ask once than spam the vault with noise or skip something that mattered.
