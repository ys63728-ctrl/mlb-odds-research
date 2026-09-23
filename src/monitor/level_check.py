"""
1分ごとに呼ばれる「判定の脳みそ」。

ふたつの判定を同時にやる:
  A. Pinnacle 単体変動  : Pinnacleが21:00基準から動いたら Level1/2/3 通知
  B. Steam Move 検知    : 同じ試合・同じチームで、自分の21:00基準から
                          同方向に STEAM_THRESHOLD 以上動いてるブックが
                          STEAM_MIN_BOOKS 以上同時に存在する瞬間に通知

設計のポイント:
- "状態が変わった瞬間" だけ通知（毎分しつこく出さない）。状態は MonitorState
  オブジェクトで保持し、再起動するとリセットされる（Phase1の仕様）。
- DB の alerts テーブルにも各イベントを記録（Steam通知は参加ブックごとに行を作る）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src import config
from src.db.models import Alert
from src.utils.odds_utils import american_to_decimal


# =====================================================================
# データクラス
# =====================================================================
@dataclass
class MonitorState:
    """通知の重複を防ぐためのメモリ上の状態。"""
    pinnacle_levels: dict[str, tuple[str, int]] = field(default_factory=dict)
    # game_id -> (team, level)  … 試合ごとに「変動が大きい側」1枠だけを保持する。
    # 同一カードは表裏で必ず両方動くため、通知は大きい側1件に集約する。

    steam_directions: dict[tuple[str, str], str | None] = field(default_factory=dict)
    # (game_id, team) -> 'up' | 'down' | None


@dataclass
class NotificationEvent:
    """1件の通知に必要なデータ。Discord(段階⑤)が文面を組み立てる。"""
    kind: str               # 'pinnacle_level' | 'pinnacle_clear' | 'steam_move' | 'steam_clear'
    game_name: str
    team: str
    note: str = ""          # 通知先頭に付ける補足ラベル（例 "1×2"）。空なら何も付けない。
    # --- Pinnacle 単体通知 ---
    level: int = 0
    bookmaker: str | None = None
    base_odds: float | None = None
    current_odds: float | None = None
    move: float | None = None
    point: float | None = None          # ハンデのライン値（例 +1.0）。h2hでは None
    # --- Steam Move 通知 ---
    direction: str | None = None        # 'up' | 'down'
    books: list[dict] = field(default_factory=list)
    # books = [{"bookmaker": "X", "base": 1.50, "current": 1.55, "move": +0.05}, ...]


# =====================================================================
# ヘルパー
# =====================================================================
def get_level(move: float) -> int:
    """絶対変動量を Level 0〜7 に変換（該当する最大のレベルを返す）。"""
    d = abs(move)
    level = 0
    for lvl, threshold in config.LEVEL_THRESHOLDS:
        if d >= threshold:
            level = lvl
    return level


def _extract_current_odds(game: dict) -> dict[tuple[str, str], float]:
    """game から (bookmaker, team) -> decimal の辞書を作る（h2h用）。"""
    result: dict[tuple[str, str], float] = {}
    for bookmaker in game.get("bookmakers", []) or []:
        if not isinstance(bookmaker, dict):
            continue
        book = bookmaker.get("title")
        if not book:
            continue
        for market in bookmaker.get("markets", []) or []:
            for outcome in market.get("outcomes", []) or []:
                team = outcome.get("name")
                price = outcome.get("price")
                if team is None or price is None:
                    continue
                result[(book, team)] = american_to_decimal(price)
    return result


def _extract_handicap_current(
    game: dict,
    game_id: str,
    base_points: dict[tuple[str, str, str], float],
) -> dict[tuple[str, str], float]:
    """
    ハンデ用。各ブック/チームについて『基準で選んだ point の現在価格』だけを取り出す。
    こうすると、価格変動もライン移動も、その固定pointの価格のブレとして検知できる。
    返り値: (bookmaker, team) -> decimal
    """
    result: dict[tuple[str, str], float] = {}
    for bookmaker in game.get("bookmakers", []) or []:
        if not isinstance(bookmaker, dict):
            continue
        book = bookmaker.get("title")
        if not book:
            continue
        for market in bookmaker.get("markets", []) or []:
            if market.get("key") != "alternate_spreads":
                continue
            for outcome in market.get("outcomes", []) or []:
                team = outcome.get("name")
                point = outcome.get("point")
                price = outcome.get("price")
                if team is None or point is None or price is None:
                    continue
                bp = base_points.get((game_id, book, team))
                if bp is None:
                    continue
                try:
                    if abs(float(point) - float(bp)) < 1e-9:
                        result[(book, team)] = american_to_decimal(price)
                except (TypeError, ValueError):
                    continue
    return result


# =====================================================================
# メイン判定
# =====================================================================
def evaluate(
    session: Session,
    games: list[dict],
    base_odds_map: dict[tuple[str, str, str], float],
    state: MonitorState,
    *,
    alert_time: datetime,
    sport: str | None = None,
    base_points: dict[tuple[str, str, str], float] | None = None,
) -> list[NotificationEvent]:
    """
    現在の games と 基準オッズ・状態 を使って判定を行い、
    新たに発生した通知イベントのリストを返す。
    同時に DB の alerts テーブルにも記録する。

    Args:
        session     : DB セッション（呼び出し側で commit）
        games       : The Odds API の返答 (現在オッズ)
        base_odds_map: 基準オッズ辞書 (load_base_odds_map で取得)
        state       : メモリ上の通知状態（更新される）
        alert_time  : この判定の時刻（JST tz-aware）
        sport       : 競技キー（省略時は config.SPORT_KEY）。Alert に記録される。

    Returns:
        新規発生した NotificationEvent のリスト
    """
    sport = sport or config.SPORT_KEY
    events: list[NotificationEvent] = []
    alert_time_naive = (
        alert_time.replace(tzinfo=None) if alert_time.tzinfo else alert_time
    )

    for game in games:
        if not isinstance(game, dict):
            continue
        game_id = game.get("id") or ""
        if not game_id:
            continue
        away = game.get("away_team", "")
        home = game.get("home_team", "")
        game_name = f"{away} vs {home}"

        if base_points is not None:
            current_by_book = _extract_handicap_current(game, game_id, base_points)
        else:
            current_by_book = _extract_current_odds(game)
        if not current_by_book:
            continue

        teams_in_game = {team for (_, team) in current_by_book.keys()}

        # A. Pinnacle 単体変動 … 同一カードは「変動が大きい側」だけを1件通知する。
        _check_pinnacle(
            session, events, state,
            game_id, game_name, teams_in_game,
            current_by_book, base_odds_map,
            alert_time_naive, sport, base_points,
        )

        # B. Steam Move … 従来どおりチームごとに判定（要望対象外）。
        for team in teams_in_game:
            _check_steam(
                session, events, state,
                game_id, game_name, team,
                current_by_book, base_odds_map,
                alert_time_naive, sport, base_points,
            )

    return events


def _check_pinnacle(
    session: Session,
    events: list[NotificationEvent],
    state: MonitorState,
    game_id: str,
    game_name: str,
    teams_in_game: set[str],
    current_by_book: dict[tuple[str, str], float],
    base_odds_map: dict[tuple[str, str, str], float],
    alert_time_naive: datetime,
    sport: str,
    base_points: dict[tuple[str, str, str], float] | None = None,
) -> None:
    """
    A. Pinnacle 単体変動の判定（試合ごとに1件）。

    同じカードは表裏で必ず両方動く（例: ドジャース↑ならレッズ↓）ため、
    Pinnacle の各チーム側の変動量を比べ、|変動量| が最大の「大きい側」だけを
    1件だけ通知・記録する。解除・レベル変化・大きい側の入れ替わりも
    この1枠(state.pinnacle_levels[game_id]=(team, level))で追従する。
    """
    pinn_book = config.PRIMARY_BOOKMAKER

    # 各チーム側の Pinnacle 変動量を集める
    candidates: list[tuple[str, float, float, float, int]] = []
    for team in teams_in_game:
        current = current_by_book.get((pinn_book, team))
        base = base_odds_map.get((game_id, pinn_book, team))
        if current is None or base is None:
            continue
        move = round(current - base, 2)
        candidates.append((team, move, current, base, get_level(move)))

    if not candidates:
        return

    old = state.pinnacle_levels.get(game_id)  # (team, level) or None
    stored_team = old[0] if old else None

    # 「変動が大きい側」を選ぶ。同点のときは、直前に通知した側を優先（解除を正しく拾うため）。
    dominant = max(
        candidates,
        key=lambda c: (abs(c[1]), 1 if c[0] == stored_team else 0),
    )
    team, move, current, base, new_level = dominant

    # まだ一度も通知しておらず、かつ今回も動いていない → 何もしない
    if old is None and new_level == 0:
        return
    # (通知した側, レベル) が前回と同じ → 再通知しない
    if old is not None and old == (team, new_level):
        return

    state.pinnacle_levels[game_id] = (team, new_level)
    point = base_points.get((game_id, pinn_book, team)) if base_points else None

    if new_level == 0:
        kind = "pinnacle_clear"
        alert_type_db = "level_clear"
    else:
        kind = "pinnacle_level"
        alert_type_db = f"level{new_level}"

    events.append(NotificationEvent(
        kind=kind,
        game_name=game_name,
        team=team,
        level=new_level,
        bookmaker=pinn_book,
        base_odds=base,
        current_odds=current,
        move=move,
        point=point,
    ))
    session.add(Alert(
        sport=sport,
        alert_time=alert_time_naive,
        alert_type=alert_type_db,
        game_id=game_id,
        bookmaker=pinn_book,
        team=team,
        base_odds=Decimal(str(base)),
        current_odds=Decimal(str(current)),
        move=Decimal(str(move)),
    ))


def _check_steam(
    session: Session,
    events: list[NotificationEvent],
    state: MonitorState,
    game_id: str,
    game_name: str,
    team: str,
    current_by_book: dict[tuple[str, str], float],
    base_odds_map: dict[tuple[str, str, str], float],
    alert_time_naive: datetime,
    sport: str,
    base_points: dict[tuple[str, str, str], float] | None = None,
) -> None:
    """B. Steam Move (同方向 ≥STEAM_MIN_BOOKS ブック / 2.1倍以下のみ対象) の判定。"""
    moved_up: list[dict] = []
    moved_down: list[dict] = []

    for (book, t), current in current_by_book.items():
        if t != team:
            continue
        # 2.1倍より高いサイドは対象外（片側だけ見れば十分なため）
        if current > config.STEAM_MAX_ODDS:
            continue
        base = base_odds_map.get((game_id, book, team))
        if base is None:
            continue
        move = round(current - base, 2)
        if abs(move) < config.STEAM_THRESHOLD:
            continue
        point = base_points.get((game_id, book, team)) if base_points else None
        entry = {"bookmaker": book, "base": base, "current": current, "move": move, "point": point}
        if move > 0:
            moved_up.append(entry)
        else:
            moved_down.append(entry)

    new_direction: str | None = None
    steam_books: list[dict] = []
    if len(moved_up) >= config.STEAM_MIN_BOOKS:
        new_direction = "up"
        steam_books = moved_up
    elif len(moved_down) >= config.STEAM_MIN_BOOKS:
        new_direction = "down"
        steam_books = moved_down

    old_direction = state.steam_directions.get((game_id, team))
    if new_direction == old_direction:
        return

    state.steam_directions[(game_id, team)] = new_direction

    if new_direction is None:
        events.append(NotificationEvent(
            kind="steam_clear",
            game_name=game_name,
            team=team,
            direction=old_direction,
        ))
        session.add(Alert(
            sport=sport,
            alert_time=alert_time_naive,
            alert_type="steam_clear",
            game_id=game_id,
            bookmaker="(steam)",
            team=team,
            base_odds=Decimal("0"),
            current_odds=Decimal("0"),
            move=Decimal("0"),
        ))
    else:
        events.append(NotificationEvent(
            kind="steam_move",
            game_name=game_name,
            team=team,
            direction=new_direction,
            books=steam_books,
        ))
        for b in steam_books:
            session.add(Alert(
                sport=sport,
                alert_time=alert_time_naive,
                alert_type="steam_move",
                game_id=game_id,
                bookmaker=b["bookmaker"],
                team=team,
                base_odds=Decimal(str(b["base"])),
                current_odds=Decimal(str(b["current"])),
                move=Decimal(str(b["move"])),
            ))
