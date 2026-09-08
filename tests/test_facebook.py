from pathlib import Path

import pytest

from facebook import page_slug, parse_posts

FIXTURE = (Path(__file__).parent / "fixtures" / "plugin.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url,slug",
    [
        ("https://www.facebook.com/LionSurplus", "LionSurplus"),
        ("https://www.facebook.com/LionSurplus/", "LionSurplus"),
        ("https://facebook.com/LionSurplus?ref=embed_page", "LionSurplus"),
        ("https://www.facebook.com/pg/LionSurplus/posts", "LionSurplus"),
    ],
)
def test_page_slug_parses_various_facebook_url_shapes(url, slug):
    assert page_slug(url) == slug


def test_page_slug_rejects_non_facebook_url():
    with pytest.raises(ValueError):
        page_slug("https://example.com/LionSurplus")


def test_parses_all_posts_in_fixture():
    posts = parse_posts(FIXTURE, "LionSurplus")
    assert len(posts) == 5


def test_posts_are_newest_first():
    posts = parse_posts(FIXTURE, "LionSurplus")
    timestamps = [p.posted_at for p in posts]
    assert timestamps == sorted(timestamps, reverse=True)


def test_post_ids_are_unique_pfbids():
    posts = parse_posts(FIXTURE, "LionSurplus")
    ids = [p.id for p in posts]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("pfbid") for i in ids)


def test_permalink_uses_post_id():
    posts = parse_posts(FIXTURE, "LionSurplus")
    for post in posts:
        assert post.url == f"https://www.facebook.com/LionSurplus/posts/{post.id}"


def test_extracts_post_text():
    posts = parse_posts(FIXTURE, "LionSurplus")
    newest = posts[0]
    assert "bread day" in newest.text
    assert "Penn State Bakery" in newest.text


def test_strips_html_from_text():
    posts = parse_posts(FIXTURE, "LionSurplus")
    for post in posts:
        assert "<" not in post.text
        assert ">" not in post.text


def test_preserves_line_and_paragraph_breaks():
    posts = parse_posts(FIXTURE, "LionSurplus")
    newest = posts[0]
    lines = newest.text.splitlines()
    assert any("BREAD" in line for line in lines)
    assert "Lion Paw Sourdough Boules" not in lines[0]  # split onto its own line, not run together
    assert "" in lines  # blank line between paragraphs


def test_text_only_post_has_no_image():
    posts = parse_posts(FIXTURE, "LionSurplus")
    closed_post = next(p for p in posts if "closed Wednesday" in p.text)
    assert closed_post.image_urls == ()


def test_photo_post_has_image_urls():
    posts = parse_posts(FIXTURE, "LionSurplus")
    newest = posts[0]
    assert newest.image_urls
    for url in newest.image_urls:
        assert url.startswith("https://")
        assert "scontent" in url


def test_multi_photo_post_has_all_images_deduped():
    posts = parse_posts(FIXTURE, "LionSurplus")
    multi_photo_post = next(p for p in posts if len(p.image_urls) > 1)
    assert len(multi_photo_post.image_urls) == len(set(multi_photo_post.image_urls))


def test_image_urls_do_not_include_the_page_avatar():
    # avatar images live under /v/t39.30808-1/, real post photos under -6/
    posts = parse_posts(FIXTURE, "LionSurplus")
    for post in posts:
        for url in post.image_urls:
            assert "/v/t39.30808-1/" not in url


def test_posted_at_is_a_real_unix_timestamp():
    posts = parse_posts(FIXTURE, "LionSurplus")
    for post in posts:
        assert post.posted_at > 1_700_000_000  # sometime after Nov 2023


def test_no_posts_returns_empty_list():
    assert parse_posts("<html><body>nothing here</body></html>", "LionSurplus") == []
