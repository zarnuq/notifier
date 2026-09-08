# Lion Surplus → Discord

Polls Lion Surplus' Facebook page and posts new items to a Discord channel.

Fetches via the Facebook Page Plugin (the public embed widget, not the main
walled page), which renders ~5 recent posts to a logged-out headless browser.
No Facebook account needed.

## Setup

```
uv sync
uv run playwright install chromium
cp .env.example .env   # fill in DISCORD_WEBHOOK_URL
```

## Run

```
uv run python monitor.py --dry-run   # print current posts, no state/Discord writes
uv run python monitor.py             # normal run
```

First run seeds `state.json` with the current posts and sends nothing, so
old posts don't flood the channel. After that, only genuinely new posts are
sent.

## Scheduling

Run every 15 minutes via Task Scheduler (Windows) or a systemd timer (Linux).
See `docs` in the plan for unit file details.

## Tests

```
uv run pytest
```

Parser/orchestration/embed tests run offline against a saved fixture — no
browser or network required.

## Troubleshooting

If the scraper stops finding posts (Facebook changed its markup), you'll get
a Discord warning after 6 consecutive empty polls, and the raw page HTML
lands in `debug/` for inspecting what changed.
