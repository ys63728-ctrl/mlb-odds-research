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


def in_monitor_window(
    now: datetime,
    base_hour: int | None = None,
    base_minute: int | None = None,
    end_hour: int | None = None,
    end_minute: int | None = None,
) -> bool:
    """
    渡されたJST時刻が監視ウィンドウの範囲内かどうか。
    引数を省略すると既定(MLB: 21:00〜23:59)を使う。スポーツ別の窓を判定するときは
    base/end を渡す（サッカーは 20:00〜23:59 等）。
    """
    base_hour = config.BASE_HOUR if base_hour is None else base_hour
    base_minute = config.BASE_MINUTE if base_minute is None else base_minute
    end_hour = config.END_HOUR if end_hour is None else end_hour
    end_minute = config.END_MINUTE if end_minute is None else end_minute

    start = base_hour * 60 + base_minute
    end = end_hour * 60 + end_minute
    cur = now.hour * 60 + now.minute
    if start <= end:
        # 同日内で完結する窓（例 21:00〜23:59）
        return start <= cur <= end
    # 日付をまたぐ窓（例 21:00〜翌01:00）。開始以降 or 終了以前なら窓内。
    return cur >= start or cur <= end


def window_session_date(
    now: datetime,
    base_hour: int,
    base_minute: int,
    end_hour: int,
    end_minute: int,
):
    """
    日付をまたぐ監視窓で、「今の窓が始まった日付(=基準を取った日)」を返す。

    例: 窓 21:00〜翌01:00 のとき、翌日 00:30 に呼ぶと『前日の日付』を返す。
    これにより、深夜0時をまたいでも基準(21:00に取得)を作り直さずに使い続けられる。
    またがない窓や、窓の前半（開始〜23:59）では now.date() をそのまま返す。
    """
    start = base_hour * 60 + base_minute
    end = end_hour * 60 + end_minute
    cur = now.hour * 60 + now.minute
    if start > end and cur <= end:
        # 日跨ぎ窓の「翌日側(0:00〜終了時刻)」にいる → 窓の開始は前日
        return (now - timedelta(days=1)).date()
    return now.date()


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
