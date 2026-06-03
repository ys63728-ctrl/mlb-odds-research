"""
時刻ユーティリティ。

方針:
- 内部処理は UTC（協定世界時）で統一
- 「監視時間内か？」「基準は何時か？」など、人間向けの判定は JST（日本時間）
- 上の境界をまたぐ変換だけをここに集約する
"""

from datetime import datetime, timezone, timedelta

from src import config


def now_jst() -> datetime:
    """現在時刻をJSTで返す。"""
    return datetime.now(config.JST)


def now_utc() -> datetime:
    """現在時刻をUTCで返す。"""
    return datetime.now(timezone.utc)


def parse_commence_time(iso_str: str) -> datetime:
    """
    The Odds API の commence_time（"2026-05-28T23:00:00Z"のような文字列）を
    UTCのdatetimeに変換する。
    """
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def in_monitor_window(now: datetime) -> bool:
    """
    渡されたJST時刻が監視ウィンドウ(21:00〜23:59)の範囲内かどうか。
    """
    h, m = now.hour, now.minute
    after_start = (h > config.BASE_HOUR) or (h == config.BASE_HOUR and m >= config.BASE_MINUTE)
    before_end = (h < config.END_HOUR) or (h == config.END_HOUR and m <= config.END_MINUTE)
    return after_start and before_end


def in_pregame_window(
    commence_time: datetime,
    now: datetime | None = None,
    *,
    lead_minutes: int,
    cutoff_minutes: int,
) -> bool:
    """
    「いまが、ある試合の開始 lead_minutes 分前 〜 cutoff_minutes 分前の範囲内か」を判定する。

    NPB方式の試合ごと監視窓に使う。例: lead=90, cutoff=5 なら
    「開始90分前から開始5分前まで」が True。

    commence_time / now はどちらも UTC（tz-aware）を想定。
    now を省略すると現在UTCを使う。テスト時は now を渡して固定できる。
    """
    if now is None:
        now = now_utc()
    window_start = commence_time - timedelta(minutes=lead_minutes)
    window_end = commence_time - timedelta(minutes=cutoff_minutes)
    return window_start <= now <= window_end


def is_within_24h(commence_time: datetime, now: datetime | None = None) -> bool:
    """
    試合開始時刻が「現在から TARGET_HOURS(=24時間) 以内」かどうか。
    now を渡せばテスト時に固定の現在時刻で判定できる。
    """
    if now is None:
        now = now_utc()
    return now <= commence_time <= now + timedelta(hours=config.TARGET_HOURS)
