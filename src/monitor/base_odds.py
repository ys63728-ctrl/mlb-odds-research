"""
「基準オッズ」をDBに保存・読み込みする。

ふたつの保存方式に対応する:

1. 固定時刻方式（MLB）:
   毎日 JST21:00 に、24時間以内に始まる全試合の基準を一括保存する。
   → create_base_odds() / has_base_odds_for_date()

2. 試合ごと方式（NPB）:
   試合が監視窓（開始90分前）に入った瞬間に、その試合1つ分だけ基準を保存する。
   → create_base_odds_for_game() / has_base_odds_for_game()

設計メモ:
- 基準オッズは Pinnacle 1社だけでなく、API が返す**全ブック分**を保存する。
  Steam Move 検知では各ブック自身の基準が必要だから。
- どちらの方式も、保存済みかを先にチェックしてから呼ぶこと（二重保存を防ぎ、
  再起動しても基準が動かないようにするため）。
- sport を省略すると config.SPORT_KEY を使う（既存のMLB呼び出しと互換）。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import config
from src.db.models import BaseOdds
from src.utils.odds_utils import american_to_decimal, pick_balanced_line
from src.utils.time_utils import parse_commence_time, is_within_24h, now_utc


def _save_one_game_base(
    session: Session,
    game: dict,
    base_date: date,
    sport: str,
) -> int:
    """
    1試合分の基準オッズ（全ブック・全アウトカム）を BaseOdds に追加する。

    commence_time が無い・壊れている試合はスキップする。
    Returns: 追加した行数。
    """
    if not isinstance(game, dict):
        return 0
    commence_str = game.get("commence_time")
    if not commence_str:
        return 0
    try:
        commence = parse_commence_time(commence_str)
    except Exception:
        return 0

    game_id = game.get("id") or ""
    away = game.get("away_team", "")
    home = game.get("home_team", "")
    game_name = f"{away} vs {home}"

    saved = 0
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

                row = BaseOdds(
                    sport=sport,
                    base_date=base_date,
                    game_id=game_id,
                    game_name=game_name,
                    bookmaker=book,
                    market=market_key,
                    team=team,
                    base_odds_decimal=Decimal(str(decimal_odd)),
                    commence_time=commence.replace(tzinfo=None),
                )
                session.add(row)
                saved += 1

    return saved


# =====================================================================
# 固定時刻方式（MLB）: 24時間以内の全試合をまとめて基準化
# =====================================================================
def create_base_odds(
    session: Session,
    games: list[dict],
    base_date: date,
    *,
    sport: str | None = None,
    now_utc_override: datetime | None = None,
) -> int:
    """
    The Odds API の返答 games から基準オッズを抽出して BaseOdds に保存する。
    24時間以内に始まる試合のみが対象（MLBの固定時刻方式）。

    Args:
        session: DBセッション（呼び出し側で commit する）
        games: The Odds API が返した試合一覧
        base_date: 基準日（JST日付）
        sport: 競技キー（省略時は config.SPORT_KEY）
        now_utc_override: テスト時にだけ「現在時刻」を上書きするための引数

    Returns:
        保存した行数
    """
    sport = sport or config.SPORT_KEY
    now = now_utc_override or now_utc()

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
        if not is_within_24h(commence, now=now):
            continue
        saved += _save_one_game_base(session, game, base_date, sport)

    return saved


def has_base_odds_for_date(
    session: Session, base_date: date, *, sport: str | None = None, market: str | None = None
) -> bool:
    """指定日・指定スポーツの基準オッズが既に DB にあるか（再起動耐性のチェック用）。

    market を指定すると、その市場(例 'spreads')の基準があるかだけを見る。
    """
    sport = sport or config.SPORT_KEY
    conds = [BaseOdds.base_date == base_date, BaseOdds.sport == sport]
    if market is not None:
        conds.append(BaseOdds.market == market)
    stmt = select(BaseOdds.id).where(*conds).limit(1)
    return session.execute(stmt).first() is not None


# =====================================================================
# 試合ごと方式（NPB）: 窓入りした1試合だけを基準化
# =====================================================================
def create_base_odds_for_game(
    session: Session,
    game: dict,
    base_date: date,
    *,
    sport: str | None = None,
) -> int:
    """
    1試合が監視窓に入った瞬間に、その試合の基準オッズ（全ブック）を保存する。
    24時間フィルタは掛けない（呼び出し側が「窓に入った」と判定済みのため）。

    Args:
        session: DBセッション（呼び出し側で commit する）
        game: The Odds API の試合1件
        base_date: 基準日（JST日付。NPBでは試合開始日のJST日付を渡す想定）
        sport: 競技キー（省略時は config.SPORT_KEY）

    Returns:
        保存した行数
    """
    sport = sport or config.SPORT_KEY
    return _save_one_game_base(session, game, base_date, sport)


def has_base_odds_for_game(
    session: Session, game_id: str, *, sport: str | None = None, market: str | None = None
) -> bool:
    """指定試合の基準オッズが既に DB にあるか（試合単位の二重保存防止）。

    market を指定すると、その市場(例 'spreads')の基準があるかだけを見る。
    """
    sport = sport or config.SPORT_KEY
    conds = [BaseOdds.game_id == game_id, BaseOdds.sport == sport]
    if market is not None:
        conds.append(BaseOdds.market == market)
    stmt = select(BaseOdds.id).where(*conds).limit(1)
    return session.execute(stmt).first() is not None


# =====================================================================
# 読み込み（両方式共通）
# =====================================================================
# =====================================================================
# ハンデ(spreads)方式: 各ブックの「1.9ライン」を基準にする
# =====================================================================
def _save_one_game_handicap(
    session: Session, game: dict, base_date: date, sport: str
) -> int:
    """
    1試合分について、各ブックの alternate_spreads から『1.9に最も近いライン』を選び、
    そのチーム/ライン/価格を BaseOdds に保存する（market='spreads', point付き）。
    Returns: 追加した行数。
    """
    if not isinstance(game, dict):
        return 0
    commence_str = game.get("commence_time")
    if not commence_str:
        return 0
    try:
        commence = parse_commence_time(commence_str)
    except Exception:
        return 0

    game_id = game.get("id") or ""
    away = game.get("away_team", "")
    home = game.get("home_team", "")
    game_name = f"{away} vs {home}"

    saved = 0
    for bookmaker in game.get("bookmakers", []) or []:
        if not isinstance(bookmaker, dict):
            continue
        book = bookmaker.get("title")
        if not book:
            continue
        # alternate_spreads の outcomes を集めて 1.9 ラインを選ぶ
        outcomes: list[dict] = []
        for market in bookmaker.get("markets", []) or []:
            if market.get("key") == "alternate_spreads":
                outcomes.extend(market.get("outcomes", []) or [])
        if not outcomes:
            continue
        balanced = pick_balanced_line(outcomes)
        for team, info in balanced.items():
            row = BaseOdds(
                sport=sport,
                base_date=base_date,
                game_id=game_id,
                game_name=game_name,
                bookmaker=book,
                market="spreads",
                team=team,
                base_odds_decimal=Decimal(str(info["odds_decimal"])),
                commence_time=commence.replace(tzinfo=None),
                point=Decimal(str(info["point"])),
            )
            session.add(row)
            saved += 1
    return saved


def create_base_odds_handicap(
    session: Session, games: list[dict], base_date: date, *, sport: str | None = None
) -> int:
    """24時間以内の全試合について、ハンデの1.9ライン基準を保存する（固定時刻方式）。"""
    sport = sport or config.SPORT_KEY
    saved = 0
    for game in games:
        saved += _save_one_game_handicap(session, game, base_date, sport)
    return saved


def create_base_odds_for_game_handicap(
    session: Session, game: dict, base_date: date, *, sport: str | None = None
) -> int:
    """1試合が窓に入った瞬間に、その試合のハンデ1.9ライン基準を保存する（試合ごと方式）。"""
    sport = sport or config.SPORT_KEY
    return _save_one_game_handicap(session, game, base_date, sport)


def load_base_odds_handicap(
    session: Session, base_date: date, *, sport: str | None = None
) -> dict[tuple[str, str, str], dict]:
    """
    指定日・スポーツの「ハンデ基準」を
    (game_id, bookmaker, team) -> {"point": float, "odds": float} の辞書で返す。
    判定時に「基準のpointの現在価格」を引くために point も持つ。
    """
    sport = sport or config.SPORT_KEY
    stmt = select(BaseOdds).where(
        BaseOdds.base_date == base_date,
        BaseOdds.sport == sport,
        BaseOdds.market == "spreads",
    )
    result: dict[tuple[str, str, str], dict] = {}
    for row in session.execute(stmt).scalars():
        point = float(row.point) if row.point is not None else None
        result[(row.game_id, row.bookmaker, row.team)] = {
            "point": point,
            "odds": float(row.base_odds_decimal),
        }
    return result


def load_base_odds_map(
    session: Session, base_date: date, *, sport: str | None = None
) -> dict[tuple[str, str, str], float]:
    """
    指定日・指定スポーツの基準オッズを (game_id, bookmaker, team) -> decimal の
    辞書として返す。1分ごとの判定で「現在オッズ vs 基準オッズ」を高速比較するために使う。
    """
    sport = sport or config.SPORT_KEY
    stmt = select(BaseOdds).where(
        BaseOdds.base_date == base_date,
        BaseOdds.sport == sport,
    )
    result: dict[tuple[str, str, str], float] = {}
    for row in session.execute(stmt).scalars():
        result[(row.game_id, row.bookmaker, row.team)] = float(row.base_odds_decimal)
    return result
