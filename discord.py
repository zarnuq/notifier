"""Builds and sends Discord webhook messages for new Facebook posts."""

from __future__ import annotations

import colorsys
import json
import re
import urllib.request
import zlib
from datetime import datetime, timezone

from facebook import Post, page_slug

_DESCRIPTION_LIMIT = 4096  # Discord embed description character limit
_TITLE_LIMIT = 256  # Discord embed title character limit
_TITLE_WORD_LIMIT = 12
_MAX_EMBEDS = 10  # Discord message limit


def build_embed(post: Post) -> dict:
    text = post.text
    slug = page_slug(post.url)
    color = _color_for_page(slug)
    embed = {
        "author": {"name": _author_name(slug)},
        "title": _title_from_text(text) if text else "New post",
        "url": post.url,
        "description": _build_description(post),
        "color": color,
    }
    if post.posted_at:
        embed["timestamp"] = datetime.fromtimestamp(post.posted_at, tz=timezone.utc).isoformat()

    # Discord only shows one image per embed, but embeds that share a `url`
    # get grouped into a single gallery in the message.
    images = post.image_urls[:_MAX_EMBEDS]
    if images:
        embed["image"] = {"url": images[0]}
    embeds = [embed] + [{"url": post.url, "image": {"url": image}, "color": color} for image in images[1:]]
    return {"embeds": embeds}


def _author_name(slug: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", slug)


def _color_for_page(slug: str) -> int:
    # Same page always gets the same color, so posts from different pages
    # stay visually distinguishable in a shared channel.
    hue = (zlib.crc32(slug.encode()) % 360) / 360
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.65)
    return (round(r * 255) << 16) + (round(g * 255) << 8) + round(b * 255)


def _build_description(post: Post) -> str:
    parts = []
    if post.posted_at:
        # <t:...:F/R> is Discord's timestamp markdown, localized per viewer.
        parts.append(f"🕒 <t:{post.posted_at}:F> • <t:{post.posted_at}:R>")
    if post.text:
        parts.append(post.text)
    return "\n\n".join(parts)[:_DESCRIPTION_LIMIT]


def _title_from_text(text: str, word_limit: int = _TITLE_WORD_LIMIT) -> str:
    # Posts tend to open with a short headline line before a blank line and
    # the details, so the first line alone is usually already a good title.
    first_line = text.splitlines()[0]
    words = first_line.split()
    title = " ".join(words[:word_limit])
    if len(words) > word_limit:
        title += "…"
    return _truncate(title, _TITLE_LIMIT)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def send(webhook_url: str, payload: dict) -> None:
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 300:
            raise RuntimeError(f"Discord webhook returned status {response.status}")
