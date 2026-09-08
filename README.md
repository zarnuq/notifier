# facebook-post-notifier

Polls Facebook pages (listed in `pages.txt`) and posts new items to a
Discord channel.

Fetches via the Facebook Page Plugin (the public embed widget, not the main
walled page), which renders ~5 recent posts to a logged-out headless browser.
No Facebook account needed.

## Setup

```
uv sync
uv run playwright install chromium
cp .env.example .env       # fill in DISCORD_WEBHOOK_URL
cp pages.txt.example pages.txt   # then add the pages you want to monitor
```

`pages.txt` and `.env` are both gitignored (personal to your setup — which
pages you watch is as much yours to keep private as the webhook secrets are);
`pages.txt.example` is the committed template.

Edit `pages.txt` to list the Facebook page URLs you want to monitor, one per
line (lines starting with `#` are ignored). By default every page posts to
`DISCORD_WEBHOOK_URL` and is polled once a day; override either per page:

```
https://www.facebook.com/SomePage
https://www.facebook.com/SomeOtherPage webhook=$SOMEOTHERPAGE_WEBHOOK_URL interval=15m
https://www.facebook.com/AnotherPage at="0 7 * * *"
```

- `webhook` (or a bare webhook URL with no key) overrides `DISCORD_WEBHOOK_URL`
  for that page. Prefer `$VAR_NAME` pointing at an env var defined in `.env`
  over writing the actual webhook URL here, so all secrets live in one place.
- `interval` polls on a rolling cadence since the page was last checked —
  a number plus `s`/`m`/`h`/`d` (e.g. `30s`, `15m`, `6h`, `1d`). Defaults to `1d`.
- `at` polls at exact time(s) instead, using standard 5-field cron syntax
  (minute hour day month weekday), e.g. `at="0 7 * * *"` = daily at 7am,
  `at="0 9 * * 1,5"` = 9am on Mondays and Fridays. Use `interval=` or `at=`,
  never both on the same line.

Either way, this only takes effect if the script itself is invoked at least
that often — see Scheduling below.

## Run

```
uv run python monitor.py --dry-run   # print current posts for every page, no state/Discord writes
uv run python monitor.py             # normal run, once per page in pages.txt
```

Each page gets its own state file under `state/<page-name>.json`. First run
for a page seeds its state file with the current posts and sends nothing, so
old posts don't flood the channel. After that, only genuinely new posts are
sent. A page whose fetch fails doesn't block the others from being checked.

## Scheduling

Run the script itself as often as your most demanding page needs — every
minute if any page uses `at=`, or as often as your shortest `interval`
otherwise — via cron, Task Scheduler (Windows), or a systemd timer (Linux).
Each page is throttled internally, so pages that aren't due yet just get
skipped on most invocations (cheap: no browser launch).

A lock file (`.monitor.lock`) prevents overlapping runs if one invocation
is still in progress when the next one fires (e.g. several pages due at
once take longer than the scheduling interval) — the newer invocation just
exits immediately rather than running concurrently.

## Tests

```
uv run pytest
```

Parser/orchestration/embed tests run offline against a saved fixture — no
browser or network required.

## Troubleshooting

If the scraper stops finding posts for a page (Facebook changed its markup),
you'll get a Discord warning after 6 consecutive empty polls for that page,
and the raw page HTML lands in `debug/` for inspecting what changed.
