"""
ペーパートレード（仮想ベット）の記録・決済・集計。

流れ:
  1) record_paper_bets: 判定時刻(MLB=23:30 / サッカー≒24:00)に、基準(21:00/20:00)から
     0.05以上「縮んだ(=有利化)」Pinnacleハンデを見つけ、1pt(基準倍率)ベットとして
     paper_bets に記録する。
  2) settle_paper_bets: 試合終了後、スコア(gid→(home,away))で未決済ベットをカバー判定し
     結果とptを確定する。
  3) summary: 累計/本日の損益を集計する（Discord報告用）。
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import config
from src.db.models import PaperBet
from src.monitor.level_check import _extract_handicap_current
from src.monitor.settle import settle_handicap

LEVEL1 = config.LEVEL1  # 0.05


# =====================================================================
# 記録
# =====================================================================
def record_paper_bets(
    session: Session,
    games: list[dict],
    base_odds_map: dict[tuple[str, str, str], float],
    base_points: dict[tuple[str, str, str], float],
    *,
    sport: str,
    bet_date: date,
    check_time: datetime,
    threshold: float = LEVEL1,
    book: str = config.PRIMARY_BOOKMAKER,
) -> int:
    """
    判定時刻の現在オッズ(games)を基準と比べ、基準pointの価格が threshold 以上
    「縮んだ」チームを 1pt ベットとして記録する。

    同一 (sport, bet_date, game_id, team) は二重記録しない。
    Returns: 新規記録した件数。
    """
    check_naive = check_time.replace(tzinfo=None) if check_time.tzinfo else check_time
    inserted = 0

    for game in games:
        if not isinstance(game, dict):
            continue
        game_id = game.get("id") or ""
        if not game_id:
            continue
        away = game.get("away_team", "")
        home = game.get("home_team", "")
        game_name = f"{away} vs {home}"
        commence_str = game.get("commence_time")

        # 基準pointの「現在価格」を取り出す (book, team) -> decimal
        current = _extract_handicap_current(game, game_id, base_points)

        for team in {t for (_, t) in current.keys()}:
            entry = base_odds_map.get((game_id, book, team))
            check_odds = current.get((book, team))
            point = base_points.get((game_id, book, team))
            if entry is None or check_odds is None or point is None:
                continue

            move = round(check_odds - entry, 2)
            if move > -threshold:      # 縮んでいない（有利化していない）
                continue

            # 二重記録防止
            exists = session.execute(
                select(PaperBet.id).where(
                    PaperBet.sport == sport,
                    PaperBet.bet_date == bet_date,
                    PaperBet.game_id == game_id,
                    PaperBet.team == team,
                ).limit(1)
            ).first()
            if exists:
                continue

            commence_dt = None
            if commence_str:
                try:
                    commence_dt = datetime.fromisoformat(
                        commence_str.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except Exception:
                    commence_dt = None

            session.add(PaperBet(
                sport=sport,
                bet_date=bet_date,
                game_id=game_id,
                game_name=game_name,
                team=team,
                point=Decimal(str(point)),
                entry_odds=Decimal(str(entry)),
                check_odds=Decimal(str(check_odds)),
                move=Decimal(str(move)),
                commence_time=commence_dt or check_naive,
                settled=0,
            ))
            inserted += 1

    return inserted


# =====================================================================
# 決済
# =====================================================================
def scores_lookup_from_oddsapi(scores: list[dict]) -> dict[str, tuple[int, int]]:
    """
    The Odds API /scores の生リストから {game_id: (home_score, away_score)} を作る。
    完了(completed)かつスコアが揃っている試合だけ。
    """
    out: dict[str, tuple[int, int]] = {}
    for s in scores:
        if not isinstance(s, dict) or not s.get("completed"):
            continue
        home = s.get("home_team")
        away = s.get("away_team")
        rows = s.get("scores") or []
        by_name = {r.get("name"): r.get("score") for r in rows if isinstance(r, dict)}
        try:
            hs = int(by_name[home])
            as_ = int(by_name[away])
        except (KeyError, TypeError, ValueError):
            continue
        gid = s.get("id")
        if gid:
            out[gid] = (hs, as_)
    return out


def settle_paper_bets(
    session: Session,
    results_by_gid: dict[str, tuple[int, int]],
    *,
    sport: str | None = None,
    settled_time: datetime | None = None,
) -> int:
    """
    未決済ベットのうち、results_by_gid に結果がある試合を決済する。
    Returns: 決済した件数。
    """
    now = settled_time or datetime.now(timezone.utc)
    now = now.replace(tzinfo=None) if now.tzinfo else now

    conds = [PaperBet.settled == 0]
    if sport:
        conds.append(PaperBet.sport == sport)
    open_bets = session.execute(select(PaperBet).where(*conds)).scalars().all()

    settled = 0
    for bet in open_bets:
        res = results_by_gid.get(bet.game_id)
        if res is None:
            continue
        home_score, away_score = res
        _, _, home = bet.game_name.partition(" vs ")
        team_is_home = (bet.team == home)

        result, pt = settle_handicap(
            team_is_home=team_is_home,
            home_score=home_score,
            away_score=away_score,
            point=float(bet.point),
            entry_odds=float(bet.entry_odds),
        )
        bet.result = result
        bet.pt = Decimal(str(pt))
        bet.home_score = home_score
        bet.away_score = away_score
        bet.settled = 1
        bet.settled_time = now
        settled += 1

    return settled


# =====================================================================
# 集計
# =====================================================================
def summary(session: Session, *, sport: str | None = None, bet_date: date | None = None) -> dict:
    """決済済みベットの損益集計を返す。"""
    conds = [PaperBet.settled == 1]
    if sport:
        conds.append(PaperBet.sport == sport)
    if bet_date:
        conds.append(PaperBet.bet_date == bet_date)
    bets = session.execute(select(PaperBet).where(*conds)).scalars().all()

    total_pt = 0.0
    w = l = p = hw = hl = 0
    for b in bets:
        total_pt += float(b.pt or 0)
        r = b.result
        if r == "win": w += 1
        elif r == "lose": l += 1
        elif r == "push": p += 1
        elif r == "half_win": hw += 1
        elif r == "half_lose": hl += 1

    decided = w + l + hw + hl        # push以外
    win_like = w + 0.5 * hw
    lose_like = l + 0.5 * hl
    hit = (win_like / (win_like + lose_like) * 100) if (win_like + lose_like) else 0.0

    return {
        "bets": len(bets),
        "win": w, "lose": l, "push": p, "half_win": hw, "half_lose": hl,
        "total_pt": round(total_pt, 2),
        "hit_rate": round(hit, 1),
        "decided": decided,
    }
