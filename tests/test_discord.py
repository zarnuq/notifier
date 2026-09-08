import json
import urllib.error

import pytest

import discord
from facebook import Post


def make_post(text="hello", image_url=None):
    return Post(
        id="pfbid001",
        text=text,
        url="https://www.facebook.com/LionSurplus/posts/pfbid001",
        image_url=image_url,
        posted_at=1_700_000_000,
    )


def test_embed_has_author_text_and_link():
    payload = discord.build_embed(make_post(text="bread day tomorrow"))
    embed = payload["embeds"][0]
    assert embed["author"]["name"] == "Lion Surplus"
    assert embed["description"] == "bread day tomorrow"
    assert embed["url"] == "https://www.facebook.com/LionSurplus/posts/pfbid001"


def test_embed_includes_image_when_present():
    payload = discord.build_embed(make_post(image_url="https://scontent.example/photo.jpg"))
    embed = payload["embeds"][0]
    assert embed["image"]["url"] == "https://scontent.example/photo.jpg"


def test_embed_omits_image_field_when_absent():
    payload = discord.build_embed(make_post(image_url=None))
    embed = payload["embeds"][0]
    assert "image" not in embed


def test_embed_truncates_long_text_to_discord_limit():
    long_text = "x" * 5000
    payload = discord.build_embed(make_post(text=long_text))
    embed = payload["embeds"][0]
    assert len(embed["description"]) <= 4096


def test_send_posts_json_to_webhook(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=10):
        captured["url"] = request.full_url
        captured["data"] = json.loads(request.data)
        captured["content_type"] = request.get_header("Content-type")
        return FakeResponse()

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)

    discord.send("https://discord.example/webhook", {"content": "hi"})

    assert captured["url"] == "https://discord.example/webhook"
    assert captured["data"] == {"content": "hi"}
    assert captured["content_type"] == "application/json"


def test_send_raises_on_http_error(monkeypatch):
    def fake_urlopen(request, timeout=10):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, None)

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError):
        discord.send("https://discord.example/webhook", {"content": "hi"})
