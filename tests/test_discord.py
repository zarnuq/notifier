import json
import urllib.error

import pytest

import discord
from facebook import Post


def make_post(text="hello", image_urls=()):
    return Post(
        id="pfbid001",
        text=text,
        url="https://www.facebook.com/LionSurplus/posts/pfbid001",
        image_urls=image_urls,
        posted_at=1_700_000_000,
    )


def test_embed_has_author_text_and_link():
    payload = discord.build_embed(make_post(text="bread day tomorrow"))
    embed = payload["embeds"][0]
    assert embed["author"]["name"] == "Lion Surplus"
    assert embed["description"] == "🕒 <t:1700000000:F> • <t:1700000000:R>\n\nbread day tomorrow"
    assert embed["url"] == "https://www.facebook.com/LionSurplus/posts/pfbid001"


def test_embed_description_starts_with_formatted_post_date():
    payload = discord.build_embed(make_post(text="bread day tomorrow"))
    embed = payload["embeds"][0]
    assert embed["description"].startswith("🕒 <t:1700000000:F> • <t:1700000000:R>\n\n")


def test_embed_preserves_line_breaks_in_description():
    payload = discord.build_embed(make_post(text="BREAD\nSourdough – Vienna"))
    embed = payload["embeds"][0]
    assert embed["description"].endswith("BREAD\nSourdough – Vienna")


def test_embed_title_is_first_line_of_post_and_links_to_post():
    payload = discord.build_embed(make_post(text="bread day tomorrow"))
    embed = payload["embeds"][0]
    assert embed["title"] == "bread day tomorrow"
    assert embed["url"] == "https://www.facebook.com/LionSurplus/posts/pfbid001"


def test_embed_title_ignores_lines_after_the_first():
    payload = discord.build_embed(make_post(text="Headline here\n\nBody line 1\nBody line 2"))
    embed = payload["embeds"][0]
    assert embed["title"] == "Headline here"


def test_embed_title_shortens_to_first_words_of_a_long_first_line():
    long_text = " ".join(f"word{i}" for i in range(30))
    payload = discord.build_embed(make_post(text=long_text))
    embed = payload["embeds"][0]
    assert embed["title"] == " ".join(f"word{i}" for i in range(discord._TITLE_WORD_LIMIT)) + "…"


def test_embed_falls_back_to_generic_title_when_text_is_empty():
    payload = discord.build_embed(make_post(text=""))
    embed = payload["embeds"][0]
    assert embed["title"] == "New post"
    assert embed["description"] == "🕒 <t:1700000000:F> • <t:1700000000:R>"


def test_embed_title_truncates_to_discord_limit():
    long_text = "x" * 300  # a single "word" longer than Discord's title limit
    payload = discord.build_embed(make_post(text=long_text))
    embed = payload["embeds"][0]
    assert len(embed["title"]) == 256
    assert embed["title"].endswith("…")


def test_embed_includes_timestamp_from_posted_at():
    payload = discord.build_embed(make_post())
    embed = payload["embeds"][0]
    assert embed["timestamp"] == "2023-11-14T22:13:20+00:00"


def test_embed_includes_image_when_present():
    payload = discord.build_embed(make_post(image_urls=("https://scontent.example/photo.jpg",)))
    embed = payload["embeds"][0]
    assert embed["image"]["url"] == "https://scontent.example/photo.jpg"


def test_embed_omits_image_field_when_absent():
    payload = discord.build_embed(make_post(image_urls=()))
    embed = payload["embeds"][0]
    assert "image" not in embed


def test_multiple_images_become_extra_embeds_sharing_the_post_url():
    images = ("https://scontent.example/a.jpg", "https://scontent.example/b.jpg", "https://scontent.example/c.jpg")
    payload = discord.build_embed(make_post(image_urls=images))
    embeds = payload["embeds"]

    assert len(embeds) == 3
    assert embeds[0]["image"]["url"] == images[0]
    assert embeds[0]["title"] == "hello"  # only the first embed carries title/description
    color = embeds[0]["color"]
    for embed, image in zip(embeds[1:], images[1:]):
        assert embed == {
            "url": "https://www.facebook.com/LionSurplus/posts/pfbid001",
            "image": {"url": image},
            "color": color,
        }


def test_embed_color_is_consistent_for_the_same_page():
    color_a = discord.build_embed(make_post())["embeds"][0]["color"]
    color_b = discord.build_embed(make_post(text="different text"))["embeds"][0]["color"]
    assert color_a == color_b
    assert 0 <= color_a <= 0xFFFFFF


def test_embed_color_differs_across_pages():
    lion_post = make_post()
    other_post = Post(
        id="pfbid002",
        text="hello",
        url="https://www.facebook.com/SomeOtherPage/posts/pfbid002",
        image_urls=(),
        posted_at=1_700_000_000,
    )
    color_a = discord.build_embed(lion_post)["embeds"][0]["color"]
    color_b = discord.build_embed(other_post)["embeds"][0]["color"]
    assert color_a != color_b


def test_embed_description_truncates_to_discord_limit():
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

        def read(self):
            return b""  # a real 204 body, which send() parses as "no content"

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


class _FakeResponse:
    status = 200

    def __init__(self, body=b""):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def test_post_asks_discord_to_return_the_message_and_yields_its_id(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=10):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return _FakeResponse(b'{"id": "12345"}')

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)

    message_id = discord.post("https://discord.example/webhook", {"content": "hi"})

    # Without wait=true Discord replies 204 with no body, and there'd be no id
    # to edit later.
    assert captured["url"] == "https://discord.example/webhook?wait=true"
    assert captured["method"] == "POST"
    assert message_id == "12345"


def test_post_appends_wait_to_a_url_that_already_has_a_query(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=10):
        captured["url"] = request.full_url
        return _FakeResponse(b'{"id": "1"}')

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)
    discord.post("https://discord.example/webhook?thread_id=7", {"content": "hi"})

    assert captured["url"] == "https://discord.example/webhook?thread_id=7&wait=true"


def test_edit_patches_the_message_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=10):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return _FakeResponse(b'{"id": "12345"}')

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)

    assert discord.edit("https://discord.example/webhook", "12345", {"content": "hi"}) is True
    assert captured["url"] == "https://discord.example/webhook/messages/12345"
    assert captured["method"] == "PATCH"


def test_edit_reports_a_deleted_message_rather_than_raising(monkeypatch):
    def fake_urlopen(request, timeout=10):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)

    # The caller falls back to posting fresh, so a hand-deleted message must
    # not take the run down.
    assert discord.edit("https://discord.example/webhook", "12345", {"content": "hi"}) is False


def test_edit_still_raises_on_errors_that_are_not_404(monkeypatch):
    def fake_urlopen(request, timeout=10):
        raise urllib.error.HTTPError(request.full_url, 500, "Server Error", {}, None)

    monkeypatch.setattr(discord.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError):
        discord.edit("https://discord.example/webhook", "12345", {"content": "hi"})
