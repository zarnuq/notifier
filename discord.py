"""Builds and sends Discord webhook messages for new Facebook posts."""

from __future__ import annotations

import colorsys
import json
import re
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone

from facebook import Post, page_slug

DESCRIPTION_LIMIT = 4096  # Discord embed description character limit
_TITLE_LIMIT = 256  # Discord embed title character limit
_TITLE_WORD_LIMIT = 12
_MAX_EMBEDS = 10  # Discord message limit
_USERNAME_LIMIT = 80  # Discord webhook username character limit


def build_embed(post: Post) -> dict:
    text = post.text
    slug = page_slug(post.url)
    color = _color_for_page(slug)
    embed = {
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
    # username/avatar_url override the webhook's own name and picture, so each
    # page posts as itself even when several share one webhook.
    payload = {"username": (post.author or _author_name(slug))[:_USERNAME_LIMIT], "embeds": embeds}
    if post.avatar_url:
        payload["avatar_url"] = post.avatar_url
    return payload


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
    return "\n\n".join(parts)[:DESCRIPTION_LIMIT]


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
    _request(webhook_url, payload, "POST")


def post(webhook_url: str, payload: dict) -> str | None:
    """Sends a message and returns its id, so it can be edited later.

    ?wait=true makes Discord respond with the created message instead of an
    empty 204.
    """
    separator = "&" if "?" in webhook_url else "?"
    body = _request(f"{webhook_url}{separator}wait=true", payload, "POST")
    return body.get("id") if body else None


def edit(webhook_url: str, message_id: str, payload: dict) -> bool:
    """Rewrites a previous webhook message in place.

    Returns False if the message no longer exists (deleted by hand, say), so
    the caller can fall back to posting a fresh one.
    """
    try:
        _request(f"{webhook_url}/messages/{message_id}", payload, "PATCH")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    return True


def _request(url: str, payload: dict, method: str) -> dict | None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-type": "application/json", "User-Agent": "Mozilla/5.0"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 300:
            raise RuntimeError(f"Discord webhook returned status {response.status}")
        body = response.read()
    return json.loads(body) if body else None
