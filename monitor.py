"""Entry point: polls Lion Surplus' Facebook page and posts new items to Discord.

Orchestration is dependency-injected (fetch_posts/send/alert are passed in)
so `run()` can be tested without a browser or network. `main()` wires up the
real implementations for actual use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable

from facebook import Post

FAILURE_ALERT_THRESHOLD = 6  # ~90 min at a 15-min poll interval
_SEEN_IDS_CAP = 50

DEFAULT_STATE_PATH = Path(__file__).parent / "state.json"


def run(
    fetch_posts: Callable[[], list[Post]],
    send: Callable[[Post], None],
    state_path: Path,
    alert: Callable[[str], None] | None = None,
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
                "Lion Surplus monitor found no posts on the last "
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
    return state


def _save_state(state_path: Path, state: dict) -> None:
    state_path.write_text(json.dumps(state, indent=2))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print posts instead of sending them")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args()

    _load_dotenv(Path(__file__).parent / ".env")

    import facebook

    if args.dry_run:
        for post in facebook.fetch_posts():
            print(f"[{post.id}] {post.text[:80]!r} image={post.image_url}")
        return

    import discord

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("DISCORD_WEBHOOK_URL is not set (set it in the environment or .env)")

    def send(post: Post) -> None:
        discord.send(webhook_url, discord.build_embed(post))

    def alert(message: str) -> None:
        discord.send(webhook_url, {"content": f"⚠️ {message}"})

    run(fetch_posts=facebook.fetch_posts, send=send, state_path=args.state, alert=alert)


if __name__ == "__main__":
    main()
