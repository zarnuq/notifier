import json
import os
import subprocess
import sys
from datetime import datetime

import pytest

from facebook import Post
import monitor


def make_post(id_="pfbid001", text="hello", image_urls=(), posted_at=100):
    return Post(
        id=id_,
        text=text,
        url=f"https://www.facebook.com/LionSurplus/posts/{id_}",
        image_urls=image_urls,
        posted_at=posted_at,
    )


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "state.json"


def test_load_pages_reads_urls_skipping_blanks_and_comments(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text(
        "# comment\n\nhttps://www.facebook.com/LionSurplus\nhttps://www.facebook.com/OtherPage\n"
    )

    pages = monitor._load_pages(pages_file)

    assert pages == [
        monitor.PageConfig("https://www.facebook.com/LionSurplus", None, monitor.DEFAULT_POLL_INTERVAL_SECONDS),
        monitor.PageConfig("https://www.facebook.com/OtherPage", None, monitor.DEFAULT_POLL_INTERVAL_SECONDS),
    ]


def test_load_pages_reads_per_page_webhook_override(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text("https://www.facebook.com/LionSurplus https://discord.example/webhook/one\n")

    pages = monitor._load_pages(pages_file)

    assert pages == [
        monitor.PageConfig(
            "https://www.facebook.com/LionSurplus",
            "https://discord.example/webhook/one",
            monitor.DEFAULT_POLL_INTERVAL_SECONDS,
        )
    ]


def test_load_pages_resolves_webhook_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("NYPOST_WEBHOOK_URL", "https://discord.example/webhook/resolved")
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text("https://www.facebook.com/LionSurplus webhook=$NYPOST_WEBHOOK_URL\n")

    pages = monitor._load_pages(pages_file)

    assert pages == [
        monitor.PageConfig(
            "https://www.facebook.com/LionSurplus",
            "https://discord.example/webhook/resolved",
            monitor.DEFAULT_POLL_INTERVAL_SECONDS,
        )
    ]


def test_load_pages_exits_when_webhook_env_var_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("MISSING_WEBHOOK_URL", raising=False)
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text("https://www.facebook.com/LionSurplus webhook=$MISSING_WEBHOOK_URL\n")

    with pytest.raises(SystemExit):
        monitor._load_pages(pages_file)


@pytest.mark.parametrize("value,seconds", [("30s", 30), ("15m", 900), ("6h", 21600), ("1d", 86400), ("1.5h", 5400)])
def test_load_pages_reads_interval_override(tmp_path, value, seconds):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text(f"https://www.facebook.com/LionSurplus interval={value}\n")

    pages = monitor._load_pages(pages_file)

    assert pages == [monitor.PageConfig("https://www.facebook.com/LionSurplus", None, seconds)]


def test_load_pages_reads_webhook_and_interval_together(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text("https://www.facebook.com/LionSurplus https://discord.example/webhook/one interval=15m\n")

    pages = monitor._load_pages(pages_file)

    assert pages == [monitor.PageConfig("https://www.facebook.com/LionSurplus", "https://discord.example/webhook/one", 900)]


def test_load_pages_reads_at_schedule(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text('https://www.facebook.com/LionSurplus at="0 7 * * *"\n')

    pages = monitor._load_pages(pages_file)

    assert pages == [
        monitor.PageConfig(
            "https://www.facebook.com/LionSurplus",
            None,
            monitor.DEFAULT_POLL_INTERVAL_SECONDS,
            monitor.CronSchedule("0 7 * * *"),
        )
    ]


def test_load_pages_exits_when_interval_and_at_both_given(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text('https://www.facebook.com/LionSurplus interval=15m at="0 7 * * *"\n')

    with pytest.raises(SystemExit):
        monitor._load_pages(pages_file)


def test_load_pages_exits_on_invalid_cron_expression(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text('https://www.facebook.com/LionSurplus at="not a cron expr"\n')

    with pytest.raises(SystemExit):
        monitor._load_pages(pages_file)


def test_load_pages_exits_on_invalid_interval(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text("https://www.facebook.com/LionSurplus interval=whenever\n")

    with pytest.raises(SystemExit):
        monitor._load_pages(pages_file)


def test_load_pages_exits_on_unknown_option(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text("https://www.facebook.com/LionSurplus bogus=1\n")

    with pytest.raises(SystemExit):
        monitor._load_pages(pages_file)


def test_load_pages_exits_when_file_missing(tmp_path):
    with pytest.raises(SystemExit):
        monitor._load_pages(tmp_path / "missing.txt")


def test_load_pages_exits_when_file_empty(tmp_path):
    pages_file = tmp_path / "pages.txt"
    pages_file.write_text("# only comments\n")

    with pytest.raises(SystemExit):
        monitor._load_pages(pages_file)


def test_cron_schedule_matches_exact_time():
    schedule = monitor.CronSchedule("0 7 * * *")
    assert schedule.matches(datetime(2026, 9, 8, 7, 0)) is True
    assert schedule.matches(datetime(2026, 9, 8, 7, 1)) is False
    assert schedule.matches(datetime(2026, 9, 8, 8, 0)) is False


def test_cron_schedule_matches_step_values():
    schedule = monitor.CronSchedule("0 */6 * * *")
    assert schedule.matches(datetime(2026, 9, 8, 0, 0)) is True
    assert schedule.matches(datetime(2026, 9, 8, 6, 0)) is True
    assert schedule.matches(datetime(2026, 9, 8, 7, 0)) is False


def test_cron_schedule_matches_comma_list_and_weekday():
    # Mondays and Fridays at 9:00; 2026-09-07 is a Monday
    schedule = monitor.CronSchedule("0 9 * * 1,5")
    assert schedule.matches(datetime(2026, 9, 7, 9, 0)) is True
    assert schedule.matches(datetime(2026, 9, 8, 9, 0)) is False


def test_cron_schedule_rejects_wrong_field_count():
    with pytest.raises(ValueError):
        monitor.CronSchedule("0 7 * *")


def make_page(url="https://www.facebook.com/LionSurplus", webhook_url=None, interval_seconds=900, schedule=None):
    return monitor.PageConfig(url=url, webhook_url=webhook_url, interval_seconds=interval_seconds, schedule=schedule)


def test_is_due_when_no_state_file_yet(tmp_path):
    assert monitor._is_due(make_page(), tmp_path / "missing.json") is True


def test_is_due_false_before_interval_elapses(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_polled_at": 1000}))

    assert monitor._is_due(make_page(interval_seconds=900), state_path, now=1000 + 60) is False


def test_is_due_true_after_interval_elapses(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_polled_at": 1000}))

    assert monitor._is_due(make_page(interval_seconds=900), state_path, now=1000 + 901) is True


def test_is_due_true_when_state_predates_last_polled_at_field(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"seen_ids": ["pfbid001"], "consecutive_failures": 0}))

    assert monitor._is_due(make_page(interval_seconds=900), state_path, now=1_700_000_000) is True


def test_is_due_false_when_now_does_not_match_cron_schedule(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_polled_at": 0}))
    page = make_page(schedule=monitor.CronSchedule("0 7 * * *"))

    not_7am = datetime(2026, 9, 8, 12, 0).timestamp()
    assert monitor._is_due(page, state_path, now=not_7am) is False


def test_is_due_true_when_now_matches_cron_schedule(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_polled_at": 0}))
    page = make_page(schedule=monitor.CronSchedule("0 7 * * *"))

    seven_am = datetime(2026, 9, 8, 7, 0).timestamp()
    assert monitor._is_due(page, state_path, now=seven_am) is True


def test_is_due_false_when_cron_schedule_already_ran_this_minute(tmp_path):
    seven_am = datetime(2026, 9, 8, 7, 0)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_polled_at": seven_am.timestamp() + 5}))
    page = make_page(schedule=monitor.CronSchedule("0 7 * * *"))

    assert monitor._is_due(page, state_path, now=seven_am.timestamp() + 30) is False


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


def test_acquire_lock_succeeds_when_no_lock_exists(tmp_path):
    lock_path = tmp_path / ".monitor.lock"
    assert monitor._acquire_lock(lock_path) is True
    assert lock_path.exists()


def test_acquire_lock_fails_when_holder_is_alive(tmp_path):
    lock_path = tmp_path / ".monitor.lock"
    lock_path.write_text(str(os.getpid()))  # our own pid is definitely alive

    assert monitor._acquire_lock(lock_path) is False


def test_acquire_lock_steals_lock_from_dead_pid(tmp_path):
    lock_path = tmp_path / ".monitor.lock"
    dead_process = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_process.wait()
    lock_path.write_text(str(dead_process.pid))

    assert monitor._acquire_lock(lock_path) is True
    assert lock_path.read_text() == str(os.getpid())


def test_release_lock_removes_file(tmp_path):
    lock_path = tmp_path / ".monitor.lock"
    lock_path.write_text(str(os.getpid()))

    monitor._release_lock(lock_path)

    assert not lock_path.exists()


def test_release_lock_missing_file_is_noop(tmp_path):
    monitor._release_lock(tmp_path / "missing.lock")  # must not raise
