from pathlib import Path

from facebook import parse_posts

FIXTURE = (Path(__file__).parent / "fixtures" / "plugin.html").read_text(encoding="utf-8")


def test_parses_all_posts_in_fixture():
    posts = parse_posts(FIXTURE)
    assert len(posts) == 5


def test_posts_are_newest_first():
    posts = parse_posts(FIXTURE)
    timestamps = [p.posted_at for p in posts]
    assert timestamps == sorted(timestamps, reverse=True)


def test_post_ids_are_unique_pfbids():
    posts = parse_posts(FIXTURE)
    ids = [p.id for p in posts]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("pfbid") for i in ids)


def test_permalink_uses_post_id():
    posts = parse_posts(FIXTURE)
    for post in posts:
        assert post.url == f"https://www.facebook.com/LionSurplus/posts/{post.id}"


def test_extracts_post_text():
    posts = parse_posts(FIXTURE)
    newest = posts[0]
    assert "bread day" in newest.text
    assert "Penn State Bakery" in newest.text


def test_strips_html_from_text():
    posts = parse_posts(FIXTURE)
    for post in posts:
        assert "<" not in post.text
        assert ">" not in post.text


def test_text_only_post_has_no_image():
    posts = parse_posts(FIXTURE)
    closed_post = next(p for p in posts if "closed Wednesday" in p.text)
    assert closed_post.image_url is None


def test_photo_post_has_image_url():
    posts = parse_posts(FIXTURE)
    newest = posts[0]
    assert newest.image_url is not None
    assert newest.image_url.startswith("https://")
    assert "scontent" in newest.image_url


def test_image_url_is_not_the_page_avatar():
    # avatar images live under /v/t39.30808-1/, real post photos under -6/
    posts = parse_posts(FIXTURE)
    for post in posts:
        if post.image_url:
            assert "/v/t39.30808-1/" not in post.image_url


def test_posted_at_is_a_real_unix_timestamp():
    posts = parse_posts(FIXTURE)
    for post in posts:
        assert post.posted_at > 1_700_000_000  # sometime after Nov 2023


def test_no_posts_returns_empty_list():
    assert parse_posts("<html><body>nothing here</body></html>") == []
