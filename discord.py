"""Builds and sends Discord webhook messages for new Lion Surplus posts."""

from __future__ import annotations

import json
import urllib.request

from facebook import Post

_DESCRIPTION_LIMIT = 4096  # Discord embed description character limit


def build_embed(post: Post) -> dict:
    embed = {
        "author": {"name": "Lion Surplus"},
        "description": post.text[:_DESCRIPTION_LIMIT],
        "url": post.url,
    }
    if post.image_url:
        embed["image"] = {"url": post.image_url}
    return {"embeds": [embed]}


def send(webhook_url: str, payload: dict) -> None:
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 300:
            raise RuntimeError(f"Discord webhook returned status {response.status}")
