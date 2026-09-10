"""Entry point: polls configured Facebook pages and posts new items to Discord.

Orchestration is dependency-injected (fetch_posts/send/alert are passed in)
so `run()` can be tested without a browser or network. `main()` wires up the
real implementations for actual use, once per page listed in pages.txt.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, NamedTuple

from facebook import Post, page_slug

FAILURE_ALERT_THRESHOLD = 6  # consecutive empty polls of a page before alerting
_SEEN_IDS_CAP = 50

DEFAULT_PAGES_PATH = Path(__file__).parent / "pages.txt"
DEFAULT_STATE_DIR = Path(__file__).parent / "state"
DEFAULT_LOCK_PATH = Path(__file__).parent / ".monitor.lock"
DEFAULT_POLL_INTERVAL_SECONDS = 86400  # 1 day, used when a page has no interval=


def run(
    fetch_posts: Callable[[], list[Post]],
    send: Callable[[Post], None],
    state_path: Path,
    alert: Callable[[str], None] | None = None,
    source_name: str = "The monitor",
) -> None:
    if not state_path.exists():
        _seed(fetch_posts(), state_path)
        return

    state = _load_state(state_path)
    posts = fetch_posts()

    if not posts:
        state["consecutive_failures"] += 1
        if alert is not None and state["consecutive_failures"] == FAILURE_ALERT_THRESHOLD:
            alert(
                f"{source_name} found no posts on the last "
                f"{FAILURE_ALERT_THRESHOLD} attempts. Facebook may have changed "
                "its markup — the scraper likely needs a fix."
            )
        _save_state(state_path, state)
        return

    seen = set(state["seen_ids"])
    new_posts = sorted((p for p in posts if p.id not in seen), key=lambda p: p.posted_at)

    try:
        for post in new_posts:
            send(post)
            state["seen_ids"].append(post.id)
    finally:
        state["consecutive_failures"] = 0
        state["seen_ids"] = state["seen_ids"][-_SEEN_IDS_CAP:]
        _save_state(state_path, state)


def _seed(posts: list[Post], state_path: Path) -> None:
    _save_state(state_path, {"seen_ids": [p.id for p in posts], "consecutive_failures": 0})


def _load_state(state_path: Path) -> dict:
    state = json.loads(state_path.read_text())
    state.setdefault("seen_ids", [])
    state.setdefault("consecutive_failures", 0)
    state.setdefault("last_polled_at", 0)
    return state


def _save_state(state_path: Path, state: dict) -> None:
    state["last_polled_at"] = time.time()
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2))
    tmp_path.replace(state_path)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


class PageConfig(NamedTuple):
    url: str
    webhook_url: str | None  # overrides DISCORD_WEBHOOK_URL for this page if set
    interval_seconds: float  # ignored when schedule is set
    schedule: "CronSchedule | None" = None  # exact times, e.g. at="0 7 * * *"


_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)([smhd])$", re.IGNORECASE)
_DURATION_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(value: str) -> float:
    match = _DURATION_RE.match(value.strip())
    if not match:
        raise ValueError(f"invalid duration {value!r} (expected e.g. 15m, 6h, 1d)")
    amount, unit = match.groups()
    return float(amount) * _DURATION_UNIT_SECONDS[unit.lower()]


class CronSchedule:
    """A standard 5-field cron expression (minute hour day month weekday)."""

    _FIELD_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]

    def __init__(self, expr: str):
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError(f"invalid cron expression {expr!r} (need 5 fields: minute hour day month weekday)")
        self.expr = expr
        self.minute, self.hour, self.dom, self.month, self.dow = (
            self._parse_field(field, lo, hi) for field, (lo, hi) in zip(fields, self._FIELD_RANGES)
        )

    @staticmethod
    def _parse_field(field: str, lo: int, hi: int) -> set[int]:
        values: set[int] = set()
        for part in field.split(","):
            part, _, step_str = part.partition("/")
            step = int(step_str) if step_str else 1
            if part == "*":
                start, end = lo, hi
            elif "-" in part:
                start, end = (int(x) for x in part.split("-", 1))
            else:
                start = end = int(part)
            values.update(range(start, end + 1, step))
        return values

    def matches(self, dt: datetime) -> bool:
        cron_weekday = (dt.weekday() + 1) % 7  # cron: 0=Sunday; datetime.weekday(): 0=Monday
        return (
            dt.minute in self.minute
            and dt.hour in self.hour
            and dt.day in self.dom
            and dt.month in self.month
            and cron_weekday in self.dow
        )

    def __eq__(self, other):
        return isinstance(other, CronSchedule) and self.expr == other.expr

    def __repr__(self):
        return f"CronSchedule({self.expr!r})"


def _resolve_webhook_url(value: str | None, path: Path, url: str) -> str | None:
    # $VAR_NAME defers to an env var (from .env) instead of a literal secret
    # in pages.txt, since pages.txt is meant to be safe to commit/share.
    if value is None or not value.startswith("$"):
        return value
    var_name = value[1:]
    resolved = os.environ.get(var_name)
    if not resolved:
        sys.exit(f"{path}: {url}: env var {var_name} (referenced via {value!r}) is not set")
    return resolved


def _load_pages(path: Path) -> list[PageConfig]:
    if not path.exists():
        sys.exit(f"{path} not found — add the Facebook page URLs you want to monitor, one per line")

    pages = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = shlex.split(line)
        url = fields[0]
        webhook_url = None
        interval_seconds = DEFAULT_POLL_INTERVAL_SECONDS
        interval_given = False
        schedule = None
        for field in fields[1:]:
            key, sep, value = field.partition("=")
            if not sep or field.startswith("http"):
                webhook_url = field  # bare webhook URL, no key=
            elif key == "webhook":
                webhook_url = value
            elif key == "interval":
                interval_given = True
                try:
                    interval_seconds = _parse_duration(value)
                except ValueError as exc:
                    sys.exit(f"{path}: {url}: {exc}")
            elif key == "at":
                try:
                    schedule = CronSchedule(value)
                except ValueError as exc:
                    sys.exit(f"{path}: {url}: {exc}")
            else:
                sys.exit(f"{path}: {url}: unknown option {field!r}")
        if schedule is not None and interval_given:
            sys.exit(f"{path}: {url}: use either interval= or at=, not both")
        webhook_url = _resolve_webhook_url(webhook_url, path, url)
        pages.append(
            PageConfig(url=url, webhook_url=webhook_url, interval_seconds=interval_seconds, schedule=schedule)
        )

    if not pages:
        sys.exit(f"{path} has no page URLs — add at least one Facebook page URL")
    return pages


def _is_due(page: PageConfig, state_path: Path, now: float | None = None) -> bool:
    if not state_path.exists():
        return True
    last_polled_at = json.loads(state_path.read_text()).get("last_polled_at", 0)
    now = time.time() if now is None else now

    if page.schedule is not None:
        now_dt = datetime.fromtimestamp(now)
        last_dt = datetime.fromtimestamp(last_polled_at)
        ran_this_minute = last_dt.replace(second=0, microsecond=0) == now_dt.replace(second=0, microsecond=0)
        return page.schedule.matches(now_dt) and not ran_this_minute

    return (now - last_polled_at) >= page.interval_seconds


def _acquire_lock(lock_path: Path) -> bool:
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if _lock_holder_is_alive(lock_path):
            return False
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
        except OSError:
            return False
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    return True


def _lock_holder_is_alive(lock_path: Path) -> bool:
    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError, FileNotFoundError):
        return False


def _release_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print posts instead of sending them")
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES_PATH, help="file listing page URLs, one per line")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH, help="lock file guarding against overlapping runs")
    args = parser.parse_args()

    _load_dotenv(Path(__file__).parent / ".env")

    import facebook

    pages = _load_pages(args.pages)

    if args.dry_run:
        for page in pages:
            print(f"== {page.url} ==")
            for post in facebook.fetch_posts(page.url):
                print(f"[{post.id}] {post.text[:80]!r} images={list(post.image_urls)}")
        return

    if not _acquire_lock(args.lock):
        return  # a previous run is still in progress

    try:
        import discord

        default_webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

        args.state_dir.mkdir(exist_ok=True)
        for page in pages:
            slug = page_slug(page.url)
            state_path = args.state_dir / f"{slug}.json"
            if not _is_due(page, state_path):
                continue

            webhook_url = page.webhook_url or default_webhook_url
            if not webhook_url:
                sys.exit(
                    f"No Discord webhook configured for {page.url} — set DISCORD_WEBHOOK_URL, "
                    f"or add a webhook URL after the page URL in {args.pages}"
                )

            def send(post: Post, webhook_url=webhook_url) -> None:
                discord.send(webhook_url, discord.build_embed(post))

            def alert(message: str, webhook_url=webhook_url) -> None:
                discord.send(webhook_url, {"content": f"⚠️ {message}"})

            try:
                run(
                    fetch_posts=lambda page_url=page.url: facebook.fetch_posts(page_url),
                    send=send,
                    state_path=state_path,
                    alert=alert,
                    source_name=f"The {slug} monitor",
                )
            except Exception as exc:
                # One page erroring out (e.g. a Playwright timeout) shouldn't
                # stop the rest of the configured pages from being checked.
                alert(f"The {slug} monitor crashed: {exc}")
    finally:
        _release_lock(args.lock)


if __name__ == "__main__":
    main()
