"""time_utils のテスト。"""

from datetime import datetime, timezone, timedelta

from src import config
from src.utils.time_utils import (
    parse_commence_time,
    in_monitor_window,
    in_pregame_window,
    is_within_24h,
)


def _jst(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=config.JST)


def test_parse_commence_time_z_suffix():
    dt = parse_commence_time("2026-05-28T23:00:00Z")
    assert dt == datetime(2026, 5, 28, 23, 0, 0, tzinfo=timezone.utc)


def test_in_monitor_window_at_2100_jst_is_true():
    # ちょうど21:00は監視内
    assert in_monitor_window(_jst(2026, 5, 28, 21, 0)) is True


def test_in_monitor_window_at_2359_jst_is_true():
    # ちょうど23:59も監視内
    assert in_monitor_window(_jst(2026, 5, 28, 23, 59)) is True


def test_in_monitor_window_at_2059_jst_is_false():
    # 20:59は監視外
    assert in_monitor_window(_jst(2026, 5, 28, 20, 59)) is False


def test_in_monitor_window_at_0000_jst_is_false():
    # 0:00 も監視外
    assert in_monitor_window(_jst(2026, 5, 29, 0, 0)) is False


def test_is_within_24h_true_for_game_in_12h():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    game = now + timedelta(hours=12)
    assert is_within_24h(game, now=now) is True


def test_is_within_24h_false_for_game_in_48h():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    game = now + timedelta(hours=48)
    assert is_within_24h(game, now=now) is False


def test_is_within_24h_false_for_past_game():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    game = now - timedelta(hours=1)
    assert is_within_24h(game, now=now) is False


# --- in_pregame_window (NPB方式の試合ごと窓) ---
# 試合開始を UTC 2026-05-28 09:00 に固定して各時点を判定する。
_COMMENCE = datetime(2026, 5, 28, 9, 0, tzinfo=timezone.utc)


def _pre(now_utc_dt):
    return in_pregame_window(_COMMENCE, now=now_utc_dt, lead_minutes=90, cutoff_minutes=5)


def test_pregame_exactly_90min_before_is_true():
    # ちょうど90分前 = 窓の開始。境界は含む
    assert _pre(_COMMENCE - timedelta(minutes=90)) is True


def test_pregame_exactly_5min_before_is_true():
    # ちょうど5分前 = 窓の終わり。境界は含む
    assert _pre(_COMMENCE - timedelta(minutes=5)) is True


def test_pregame_in_the_middle_is_true():
    # 30分前は窓内
    assert _pre(_COMMENCE - timedelta(minutes=30)) is True


def test_pregame_91min_before_is_false():
    # 91分前はまだ早い（窓に入っていない）
    assert _pre(_COMMENCE - timedelta(minutes=91)) is False


def test_pregame_4min_before_is_false():
    # 4分前はもう打ち切り後（窓を抜けている）
    assert _pre(_COMMENCE - timedelta(minutes=4)) is False


def test_pregame_after_start_is_false():
    # 試合開始後は当然 False
    assert _pre(_COMMENCE + timedelta(minutes=1)) is False
