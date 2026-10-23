"""Posts the day's Penn State Waring Commons menu to Discord.

Separate from monitor.py on purpose: that one diffs a feed and reports what
changed, this one is a scheduled digest of a page that's wholly replaced every
day. The shared pieces are the Discord webhook calls and the helpers in common.py.

Source is the Housing and Food Services daily menu — a plain ColdFusion POST
form, no JavaScript, so this needs no browser (unlike the Facebook scraper).
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import NamedTuple

from common import load_dotenv, write_json_atomic
from discord import DESCRIPTION_LIMIT, edit, post

MENU_URL = "https://www.absecom.psu.edu/menus/user-pages/daily-menu.cfm"
WARING = "16"  # selCampus value for "UP: West Food District @ Waring"
MEALS = ("Breakfast", "Lunch", "Dinner")

_PSU_BLUE = 0x1E407C

_MEAL_ICONS = {"Breakfast": "🥞", "Lunch": "🥪", "Dinner": "🍝"}

# Retail counters that share the West Food District building but are not the
# Waring Commons buffet — you pay for these separately. The HFS menu lumps them
# in with the commons; we drop them entirely rather than imply they're included.
# Per liveon.psu.edu the district holds exactly one buffet, "Waring Square
# Buffet @ West", plus these three retail venues. Everything else on the menu
# page (Deli, Grill, Pizza & Pasta, ...) is a station inside the buffet.
_OFF_MENU = {
    "EDGE",  # Edge @ West — coffee/cafe
    "STATE CHIK'N",  # fast casual
    "MARKET WEST",  # convenience store
}

# Buffet stations that serve the same thing every day. Folded into a single
# trailing line instead of listed — they're what makes the raw menu unreadable.
# Matching is by exact category name, so a station PSU renames or adds shows up
# in the body by default; the failure mode is a too-long post, not a silent
# omission.
_STANDING = {
    "SALAD",
    "FRUIT BAR",
    "DESSERTS/PASTRIES",
    "DELI",
    "AVAILABLE UPON REQUEST",
}

# Only diet markers that are actually selective. "Meatless" and "Halal
# Friendly" sit on most of the menu, so as per-item icons they were noise;
# halal survives as a station label instead (see _station_note).
_DIET_TAGS = {
    "Vegan": "🌱",
    "Gluten Friendly - made w/o gluten-containing items": "🌾",
}

_ITEM_RE = re.compile(
    # Bound the body to the item's own <a> plus its optional icon span. Matching
    # on the enclosing </div> instead would run past the item and pull in every
    # following item's diet icons, since the divs aren't closed one-per-item.
    r'<div class="menu-items daily-menu-item" data-menu-item-name="(?P<name>[^"]*)">'
    r'(?P<body>.*?</a>(?:\s*<span class="daily-menu-item__icons">.*?</span>)?)',
    re.DOTALL,
)
_CATEGORY_RE = re.compile(
    r'<details[^>]*class="menu-category-section".*?<span class="nutrition-category-title">(?P<title>[^<]*)</span>',
    re.DOTALL,
)
_ALT_RE = re.compile(r'alt="([^"]*)"')


class Item(NamedTuple):
    name: str
    diets: frozenset[str]  # legend alt text, e.g. "Vegan"


def fetch_meal(meal: str, when: date) -> str:
    data = urllib.parse.urlencode(
        {
            "selMenuDate": when.strftime("%m/%d/%Y"),
            "selMeal": meal,
            "selCampus": WARING,
        }
    ).encode()
    request = urllib.request.Request(
        MENU_URL, data=data, headers={"User-Agent": "Mozilla/5.0"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def parse_menu(page: str) -> list[tuple[str, list[Item]]]:
    """Returns [(category, [Item, ...]), ...] in the order the page lists them."""
    # Category headers and items are siblings in document order rather than
    # nested, so walk the page once and attach each item to the last header.
    marks = [(m.start(), 0, html.unescape(m.group("title")).strip()) for m in _CATEGORY_RE.finditer(page)]
    marks += [(m.start(), 1, _parse_item(m)) for m in _ITEM_RE.finditer(page)]
    marks.sort(key=lambda mark: mark[0])

    categories: list[tuple[str, list[Item]]] = []
    for _, kind, value in marks:
        if kind == 0:
            categories.append((value, []))
        elif categories:
            categories[-1][1].append(value)
    return [(name, items) for name, items in categories if items]


def _parse_item(match: re.Match) -> Item:
    # Some rows are leading-dot placeholders (".Fruit selection varies daily")
    # that the site uses to force sort order; the dot is noise here.
    name = html.unescape(match.group("name")).strip().lstrip(".")
    # The source has stray double spaces ("Pepperoni  Pizza").
    return Item(" ".join(name.split()), frozenset(_ALT_RE.findall(match.group("body"))))


def _features(categories: list[tuple[str, list[Item]]]) -> list[tuple[str, list[Item]]]:
    """Day-to-day stations, deduped, standing stations dropped.

    The same dish often appears under two stations (an entree is also the vegan
    option), so keep the first listing and drop later repeats. A station left
    empty by that is dropped rather than rendered as a bare header.
    """
    seen: set[str] = set()
    out = []
    for category, items in categories:
        if category.upper() in _STANDING | _OFF_MENU:
            continue
        fresh = []
        for item in items:
            key = item.name.casefold()
            if key not in seen:
                seen.add(key)
                fresh.append(item)
        if fresh:
            out.append((category, fresh))
    return out


def _standing_names(categories: list[tuple[str, list[Item]]]) -> list[str]:
    return [_titlecase(name) for name, _ in categories if name.upper() in _STANDING]


def _titlecase(name: str) -> str:
    # Source names are shouty caps. str.title alone also capitalises after an
    # apostrophe, turning "STATE CHIK'N" into "Chik'N".
    out = re.sub(r"(?<=\w)'(\w)", lambda m: "'" + m.group(1).lower(), name.title())
    return out.replace("W/", "w/ ").replace("w/  ", "w/ ").strip()


def _render_item(item: Item) -> str:
    tags = " ".join(_DIET_TAGS[diet] for diet in sorted(item.diets) if diet in _DIET_TAGS)
    return f"{item.name}  ·  {tags}" if tags else item.name


def render_meal(meal: str, categories: list[tuple[str, list[Item]]]) -> str:
    """One meal as a markdown block, grouped under its station headings."""
    # ## is Discord's heading markdown, which outranks the bold station names.
    heading = f"## {_MEAL_ICONS.get(meal, '🍽️')} {meal}"
    stations = _features(categories)
    if not stations:
        return f"{heading}\n-# not served today"

    blocks = [
        f"**{_titlecase(name)}**\n" + "\n".join(_render_item(item) for item in items)
        for name, items in stations
    ]
    return heading + "\n" + "\n\n".join(blocks)


def build_description(menus: list[tuple[str, list[tuple[str, list[Item]]]]], when: date) -> str:
    # # is Discord's largest heading, so the date reads as the message title;
    # meals sit a level below it at ##.
    blocks = [f"# {when:%A, %B %-d}"]
    blocks += [render_meal(meal, cats) for meal, cats in menus]

    standing: list[str] = []
    for _, cats in menus:
        for name in _standing_names(cats):
            if name not in standing:
                standing.append(name)
    if standing:
        # -# is Discord's small-text markdown, which de-emphasises the line.
        blocks.append("-# Always: " + ", ".join(standing))

    return "\n\n".join(blocks)[:DESCRIPTION_LIMIT]


def build_payload(menus: list[tuple[str, list[tuple[str, list[Item]]]]], when: date) -> dict:
    return {
        "embeds": [
            {
                "author": {"name": "Waring Commons"},
                "description": build_description(menus, when),
                "color": _PSU_BLUE,
                "footer": {"text": "West Food District @ Waring · 🌱 vegan · 🌾 gluten friendly"},
            }
        ]
    }


def main() -> None:
    root = Path(__file__).parent
    load_dotenv(root / ".env")
    webhook_url = os.environ.get("MENU_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("Set MENU_WEBHOOK_URL (or DISCORD_WEBHOOK_URL) in .env")

    today = date.today()
    menus = [(meal, parse_menu(fetch_meal(meal, today))) for meal in MEALS]
    if not any(categories for _, categories in menus):
        # Closed for a break or a holiday — stay quiet rather than posting an
        # empty menu every morning for weeks.
        print(f"No menu published for {today}; nothing to send.")
        return

    payload = build_payload(menus, today)
    description = payload["embeds"][0]["description"]
    if "--dry-run" in sys.argv:
        print(description)
        print(f"\n[{len(description)} chars]")
        return

    state_path = root / "state" / "menu.json"
    state = _load_state(state_path)
    digest = hashlib.sha256(description.encode()).hexdigest()[:16]
    posted_today = state.get("date") == today.isoformat()

    if posted_today and state.get("digest") == digest:
        print(f"{today} menu unchanged; nothing to do.")
        return

    # Re-runs on the same day rewrite that morning's message rather than
    # stacking duplicates — PSU does amend the menu during the day.
    if posted_today and state.get("message_id"):
        if edit(webhook_url, state["message_id"], payload):
            write_json_atomic(state_path, {**state, "digest": digest})
            print(f"Updated {today} menu in place.")
            return
        print("Previous message is gone; posting a new one.")

    message_id = post(webhook_url, payload)
    write_json_atomic(
        state_path, {"date": today.isoformat(), "digest": digest, "message_id": message_id}
    )
    print(f"Sent {today} menu.")


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}



if __name__ == "__main__":
    main()
