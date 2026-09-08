import json

import pytest

from facebook import Post
import monitor


def make_post(id_="pfbid001", text="hello", image_url=None, posted_at=100):
    return Post(
        id=id_,
        text=text,
        url=f"https://www.facebook.com/LionSurplus/posts/{id_}",
        image_url=image_url,
        posted_at=posted_at,
    )


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "state.json"


def test_first_run_seeds_without_sending(state_path):
    posts = [make_post("pfbid001"), make_post("pfbid002")]
    sent = []

    monitor.run(
        fetch_posts=lambda: posts,
        send=lambda post: sent.append(post),
        state_path=state_path,
    )

    assert sent == []
    state = json.loads(state_path.read_text())
    assert set(state["seen_ids"]) == {"pfbid001", "pfbid002"}
    assert state["consecutive_failures"] == 0


def test_unchanged_posts_send_nothing(state_path):
    posts = [make_post("pfbid001")]
    state_path.write_text(json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": 0}))
    sent = []

    monitor.run(fetch_posts=lambda: posts, send=lambda post: sent.append(post), state_path=state_path)

    assert sent == []


def test_new_post_is_sent(state_path):
    state_path.write_text(json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": 0}))
    posts = [make_post("pfbid002", posted_at=200), make_post("pfbid001", posted_at=100)]
    sent = []

    monitor.run(fetch_posts=lambda: posts, send=lambda post: sent.append(post), state_path=state_path)

    assert [p.id for p in sent] == ["pfbid002"]
    state = json.loads(state_path.read_text())
    assert set(state["seen_ids"]) == {"pfbid001", "pfbid002"}


def test_multiple_new_posts_sent_oldest_first(state_path):
    state_path.write_text(json.dumps({"seen_ids": [], "consecutive_failures": 0}))
    posts = [
        make_post("pfbid003", posted_at=300),
        make_post("pfbid002", posted_at=200),
        make_post("pfbid001", posted_at=100),
    ]
    sent = []

    monitor.run(fetch_posts=lambda: posts, send=lambda post: sent.append(post), state_path=state_path)

    assert [p.id for p in sent] == ["pfbid001", "pfbid002", "pfbid003"]


def test_failed_send_does_not_mark_post_seen(state_path):
    state_path.write_text(json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": 0}))
    posts = [make_post("pfbid002", posted_at=200), make_post("pfbid001", posted_at=100)]

    def failing_send(post):
        raise RuntimeError("discord is down")

    with pytest.raises(RuntimeError):
        monitor.run(fetch_posts=lambda: posts, send=failing_send, state_path=state_path)

    state = json.loads(state_path.read_text())
    assert "pfbid002" not in state["seen_ids"]


def test_failure_counter_resets_on_success(state_path):
    state_path.write_text(json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": 3}))
    posts = [make_post("pfbid001")]

    monitor.run(fetch_posts=lambda: posts, send=lambda post: None, state_path=state_path)

    state = json.loads(state_path.read_text())
    assert state["consecutive_failures"] == 0


def test_empty_fetch_increments_failure_counter(state_path):
    state_path.write_text(json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": 2}))

    monitor.run(fetch_posts=lambda: [], send=lambda post: None, state_path=state_path)

    state = json.loads(state_path.read_text())
    assert state["consecutive_failures"] == 3


def test_breakage_alert_fires_after_threshold(state_path):
    state_path.write_text(
        json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": monitor.FAILURE_ALERT_THRESHOLD - 1})
    )
    alerts = []

    monitor.run(
        fetch_posts=lambda: [],
        send=lambda post: None,
        state_path=state_path,
        alert=lambda msg: alerts.append(msg),
    )

    assert len(alerts) == 1


def test_breakage_alert_does_not_fire_before_threshold(state_path):
    state_path.write_text(json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": 0}))
    alerts = []

    monitor.run(
        fetch_posts=lambda: [],
        send=lambda post: None,
        state_path=state_path,
        alert=lambda msg: alerts.append(msg),
    )

    assert alerts == []


def test_breakage_alert_only_fires_once_per_outage(state_path):
    state_path.write_text(
        json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": monitor.FAILURE_ALERT_THRESHOLD})
    )
    alerts = []

    monitor.run(
        fetch_posts=lambda: [],
        send=lambda post: None,
        state_path=state_path,
        alert=lambda msg: alerts.append(msg),
    )

    assert alerts == []
