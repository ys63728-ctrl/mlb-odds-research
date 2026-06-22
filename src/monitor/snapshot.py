"""
5分ごとに、全試合・全ブックのオッズスナップショットを DB に保存する。

設計メモ:
- 1分ごとの API ポーリングで取った最新データを、5分に1回だけここに通せばよい
  （API は呼び直さない＝追加クレジット消費なし）。
- 24時間以内の試合のみ保存。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src import config
from src.db.models import OddsSnapshot
from src.utils.odds_utils import american_to_decimal, decimal_to_american, pick_balanced_line
from src.utils.time_utils import parse_commence_time, is_within_24h, now_utc


def save_snapshot(
    session: Session,
    games: list[dict],
    snapshot_time_jst: datetime,
    *,
    sport: str | None = None,
    now_utc_override: datetime | None = None,
) -> int:
    """
    games を全ブック・全アウトカム分 OddsSnapshot として保存する。

    Args:
        session: DBセッション
        games: The Odds API が返した試合一覧
        snapshot_time_jst: スナップショットを撮った JST 時刻
        sport: 競技キー（省略時は config.SPORT_KEY）
        now_utc_override: テスト時用

    Returns:
        保存した行数
    """
    sport = sport or config.SPORT_KEY
    saved = 0
    now = now_utc_override or now_utc()

    # SQLite は naive datetime を期待するので、tzinfo を落として保存する
    snap_naive = (
        snapshot_time_jst.replace(tzinfo=None)
        if snapshot_time_jst.tzinfo is not None
        else snapshot_time_jst
    )

    for game in games:
        if not isinstance(game, dict):
            continue
        commence_str = game.get("commence_time")
        if not commence_str:
            continue
        try:
            commence = parse_commence_time(commence_str)
        except Exception:
            continue
        if not is_within_24h(commence, now=now):
            continue

        game_id = game.get("id") or ""
        away = game.get("away_team", "")
        home = game.get("home_team", "")
        game_name = f"{away} vs {home}"

        for bookmaker in game.get("bookmakers", []) or []:
            if not isinstance(bookmaker, dict):
                continue
            book = bookmaker.get("title")
            if not book:
                continue
            for market in bookmaker.get("markets", []) or []:
                market_key = market.get("key", "h2h")
                for outcome in market.get("outcomes", []) or []:
                    team = outcome.get("name")
                    price = outcome.get("price")
                    if team is None or price is None:
                        continue
                    decimal_odd = american_to_decimal(price)
                    point = outcome.get("point")

                    row = OddsSnapshot(
                        sport=sport,
                        snapshot_time=snap_naive,
                        game_id=game_id,
                        game_name=game_name,
                        away_team=away,
                        home_team=home,
                        commence_time=commence.replace(tzinfo=None),
                        bookmaker=book,
                        market=market_key,
                        team=team,
                        odds_decimal=Decimal(str(decimal_odd)),
                        odds_american=int(price),
                        point=Decimal(str(point)) if point is not None else None,
                    )
                    session.add(row)
                    saved += 1

    return saved


def save_snapshot_handicap(
    session: Session,
    games: list[dict],
    snapshot_time_jst: datetime,
    *,
    sport: str | None = None,
) -> int:
    """
    各試合・各ブックの『1.9ライン』だけをスナップショット保存する（market='spreads'）。
    全ハンデ階段を保存すると膨大になるため、監視対象の1.9ラインに絞る。
    """
    sport = sport or config.SPORT_KEY
    snap_naive = (
        snapshot_time_jst.replace(tzinfo=None)
        if snapshot_time_jst.tzinfo is not None
        else snapshot_time_jst
    )

    saved = 0
    for game in games:
        if not isinstance(game, dict):
            continue
        commence_str = game.get("commence_time")
        if not commence_str:
            continue
        try:
            commence = parse_commence_time(commence_str)
        except Exception:
            continue

        game_id = game.get("id") or ""
        away = game.get("away_team", "")
        home = game.get("home_team", "")
        game_name = f"{away} vs {home}"

        for bookmaker in game.get("bookmakers", []) or []:
            if not isinstance(bookmaker, dict):
                continue
            book = bookmaker.get("title")
            if not book:
                continue
            outcomes: list[dict] = []
            for market in bookmaker.get("markets", []) or []:
                if market.get("key") == "alternate_spreads":
                    outcomes.extend(market.get("outcomes", []) or [])
            if not outcomes:
                continue
            for team, info in pick_balanced_line(outcomes).items():
                dec = info["odds_decimal"]
                row = OddsSnapshot(
                    sport=sport,
                    snapshot_time=snap_naive,
                    game_id=game_id,
                    game_name=game_name,
                    away_team=away,
                    home_team=home,
                    commence_time=commence.replace(tzinfo=None),
                    bookmaker=book,
                    market="spreads",
                    team=team,
                    odds_decimal=Decimal(str(dec)),
                    odds_american=decimal_to_american(dec),
                    point=Decimal(str(info["point"])),
                )
                session.add(row)
                saved += 1

    return saved
