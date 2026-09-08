"""Fetches and parses posts from Lion Surplus' Facebook page.

Facebook blocks plain HTTP requests and walls its main page behind a login
dialog after one post. The Facebook Page Plugin (the embeddable widget FB
provides for sites like surplus.psu.edu) has neither problem: it's a public
embed surface that renders ~5 posts to a logged-out browser.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

DEBUG_DIR = Path(__file__).parent / "debug"

PLUGIN_URL = (
    "https://www.facebook.com/plugins/page.php"
    "?href=https%3A%2F%2Fwww.facebook.com%2FLionSurplus"
    "&tabs=timeline&width=500&height=2000"
    "&small_header=true&adapt_container_width=true"
    "&hide_cover=false&show_facepile=false"
)

# One per post; a legacy, non-hashed class combo that has stayed stable
# across the plugin's classic HTML rendering path.
_POST_BLOCK_MARKER = '<div class="_4-u2 mbm _4mrt _5jmm _5pat _5v3q _7cqq _4-u8"'
_PERMALINK_RE = re.compile(r"/LionSurplus/posts/(pfbid[A-Za-z0-9]+)")
_UTIME_RE = re.compile(r'data-utime="(\d+)"')
_POST_MESSAGE_MARKER = 'data-testid="post_message"'
# t39.30808-6 is Facebook's CDN path segment for timeline photos;
# t39.30808-1 is profile/avatar pictures. This tells them apart without
# needing the image to actually load.
_IMAGE_RE = re.compile(r'src="([^"]*?/v/t39\.30808-6/[^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Post:
    id: str
    text: str
    url: str
    image_url: str | None
    posted_at: int  # unix epoch seconds


def fetch_posts() -> list[Post]:
    """Fetches the current posts by rendering the Page Plugin in a headless browser."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(PLUGIN_URL, wait_until="networkidle")
            page.wait_for_selector('a[href*="pfbid"]', timeout=15_000)
            content = page.content()
        finally:
            browser.close()

    posts = parse_posts(content)
    if not posts:
        _dump_debug_html(content)
    return posts


def _dump_debug_html(content: str) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (DEBUG_DIR / f"empty-fetch-{stamp}.html").write_text(content, encoding="utf-8")


def parse_posts(html: str) -> list[Post]:
    """Parses posts out of rendered Page Plugin HTML. Pure function, no I/O."""
    blocks = html.split(_POST_BLOCK_MARKER)[1:]
    posts: list[Post] = []
    seen: set[str] = set()
    for block in blocks:
        match = _PERMALINK_RE.search(block)
        if not match:
            continue
        post_id = match.group(1)
        if post_id in seen:
            continue
        seen.add(post_id)
        posts.append(_parse_block(post_id, block))
    return posts


def _parse_block(post_id: str, block: str) -> Post:
    utime_match = _UTIME_RE.search(block)
    posted_at = int(utime_match.group(1)) if utime_match else 0

    image_match = _IMAGE_RE.search(block)
    image_url = html_lib.unescape(image_match.group(1)) if image_match else None

    return Post(
        id=post_id,
        text=_extract_post_text(block),
        url=f"https://www.facebook.com/LionSurplus/posts/{post_id}",
        image_url=image_url,
        posted_at=posted_at,
    )


def _extract_post_text(block: str) -> str:
    marker_idx = block.find(_POST_MESSAGE_MARKER)
    if marker_idx == -1:
        return ""
    div_start = block.rfind("<div", 0, marker_idx)
    content = _balanced_div_content(block, div_start)
    text = _TAG_RE.sub(" ", content)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _balanced_div_content(chunk: str, div_start: int) -> str:
    """Returns the inner HTML of the <div> opening at div_start, respecting nesting."""
    content_start = chunk.index(">", div_start) + 1
    depth = 1
    i = content_start
    while True:
        open_idx = chunk.find("<div", i)
        close_idx = chunk.find("</div>", i)
        if close_idx == -1:
            return chunk[content_start:]
        if open_idx != -1 and open_idx < close_idx:
            depth += 1
            i = open_idx + 4
        else:
            depth -= 1
            i = close_idx + 6
            if depth == 0:
                return chunk[content_start:close_idx]
