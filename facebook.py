"""Fetches and parses posts from a Facebook page.

Facebook blocks plain HTTP requests and walls its main page behind a login
dialog after one post. The Facebook Page Plugin (the embeddable widget FB
provides for sites like surplus.psu.edu) has neither problem: it's a public
embed surface that renders ~5 posts to a logged-out browser.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEBUG_DIR = Path(__file__).parent / "debug"

_PAGE_SLUG_RE = re.compile(r"facebook\.com/(?:pg/)?([^/?#]+)", re.IGNORECASE)

# One per post; a legacy, non-hashed class combo that has stayed stable
# across the plugin's classic HTML rendering path.
_POST_BLOCK_MARKER = '<div class="_4-u2 mbm _4mrt _5jmm _5pat _5v3q _7cqq _4-u8"'
_UTIME_RE = re.compile(r'data-utime="(\d+)"')
_POST_MESSAGE_MARKER = 'data-testid="post_message"'
# t39.30808-6 is Facebook's CDN path segment for timeline photos;
# t39.30808-1 is profile/avatar pictures. This tells them apart without
# needing the image to actually load.
_IMAGE_RE = re.compile(r'src="([^"]*?/v/t39\.30808-6/[^"]*)"')
_AVATAR_RE = re.compile(r'<img[^>]*src="([^"]*?/v/t39\.30808-1/[^"]*)"[^>]*aria-label="([^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_PARAGRAPH_END_RE = re.compile(r"</p>", re.IGNORECASE)


@dataclass(frozen=True)
class Post:
    id: str  # stable across polls, unlike the pfbid in url
    text: str
    url: str
    image_urls: tuple[str, ...]
    posted_at: int  # unix epoch seconds
    author: str = ""  # page display name, e.g. "Lion Surplus"
    avatar_url: str = ""


def page_slug(page_url: str) -> str:
    """Extracts the page name from a Facebook page URL"""
    match = _PAGE_SLUG_RE.search(page_url)
    if not match:
        raise ValueError(f"Not a Facebook page URL: {page_url!r}")
    return match.group(1)


def _plugin_url(page_url: str) -> str:
    encoded = urllib.parse.quote(page_url, safe="")
    return (
        "https://www.facebook.com/plugins/page.php"
        f"?href={encoded}"
        "&tabs=timeline&width=500&height=2000"
        "&small_header=true&adapt_container_width=true"
        "&hide_cover=false&show_facepile=false"
    )


def fetch_posts(page_url: str) -> list[Post]:
    """Fetches the current posts by rendering the Page Plugin in a headless browser."""
    # Imported here so the parsing helpers (and menu.py, via discord.py) don't
    # need Playwright installed.
    from playwright.sync_api import sync_playwright

    slug = page_slug(page_url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            # The plugin's own JS no longer inserts the timeline into the DOM, so read the XHR that carries it.
            with page.expect_response(lambda r: "/plugin/tab/renderer/" in r.url, timeout=15_000) as resp:
                page.goto(_plugin_url(page_url), wait_until="networkidle")
            content = _renderer_markup(resp.value.text())
        finally:
            browser.close()

    posts = parse_posts(content, slug)
    if not posts:
        _dump_debug_html(content, slug)
    return posts


def _renderer_markup(body: str) -> str:
    """Extracts the timeline HTML from a tab/renderer response body."""
    return json.loads(body.removeprefix("for (;;);"))["payload"]["content"]["markup"]["__html"]


def _dump_debug_html(content: str, slug: str) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (DEBUG_DIR / f"empty-fetch-{slug}-{stamp}.html").write_text(content, encoding="utf-8")


def parse_posts(html: str, slug: str) -> list[Post]:
    """Parses posts out of rendered Page Plugin HTML. Pure function, no I/O."""
    permalink_re = re.compile(rf"/{re.escape(slug)}/posts/(pfbid[A-Za-z0-9]+)")
    blocks = html.split(_POST_BLOCK_MARKER)[1:]
    posts: list[Post] = []
    seen: set[str] = set()
    for block in blocks:
        match = permalink_re.search(block)
        if not match:
            continue
        post = _parse_block(match.group(1), block, slug)
        if post.id in seen:
            continue
        seen.add(post.id)
        posts.append(post)
    return posts


def _parse_block(permalink_id: str, block: str, slug: str) -> Post:
    utime_match = _UTIME_RE.search(block)
    posted_at = int(utime_match.group(1)) if utime_match else 0
    text = _extract_post_text(block)
    avatar_match = _AVATAR_RE.search(block)

    return Post(
        id=_stable_id(posted_at, text),
        text=text,
        url=f"https://www.facebook.com/{slug}/posts/{permalink_id}",
        image_urls=_extract_image_urls(block),
        posted_at=posted_at,
        author=html_lib.unescape(avatar_match.group(2)) if avatar_match else "",
        avatar_url=html_lib.unescape(avatar_match.group(1)) if avatar_match else "",
    )


def _stable_id(posted_at: int, text: str) -> str:
    # Facebook re-encodes a post's pfbid on every render, so it identifies the
    # permalink but not the post; data-utime is the same on every fetch.
    if posted_at:
        return str(posted_at)
    return "t" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _extract_image_urls(block: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(html_lib.unescape(url) for url in _IMAGE_RE.findall(block)))


def _extract_post_text(block: str) -> str:
    marker_idx = block.find(_POST_MESSAGE_MARKER)
    if marker_idx == -1:
        return ""
    div_start = block.rfind("<div", 0, marker_idx)
    content = _balanced_div_content(block, div_start)
    # <br> and </p> carry the post's real line/paragraph breaks; every other
    # tag is stripped, so those breaks must be captured before the tag-strip.
    content = _BR_RE.sub("\n", content)
    content = _PARAGRAPH_END_RE.sub("\n\n", content)
    text = _TAG_RE.sub(" ", content)
    text = html_lib.unescape(text)
    return _normalize_whitespace(text)


def _normalize_whitespace(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
