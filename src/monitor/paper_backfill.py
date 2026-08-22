"""
ペーパートレード台帳(paper_bets)の初回バックフィル。

既存の base_odds(21:00/20:00基準) と odds_snapshots(判定時刻の価格) から、
過去ぶんの「有利化(縮み≥0.05)したPinnacleハンデ」を1ptベットとして記録し、
試合結果で決済する。

  - 記録: 各スポーツの判定時刻(MLB=23:30 / サッカー=23:59)に最も近いスナップと基準を比較
  - 決済: MLB=MLB Stats API(日付・チーム名で照合) / サッカー=The Odds API /scores(直近3日)
  - 二重記録・二重決済はしない(冪等)。何度実行しても安全。
"""

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from src import config
from src.db.database import get_session, init_db
from src.db.models import BaseOdds, OddsSnapshot, PaperBet
from src.monitor.paper_trade import settle_paper_bets, scores_lookup_from_oddsapi
from src.api.odds_api import get_scores
from src.api.mlb_api import get_schedule

BOOK = config.PRIMARY_BOOKMAKER
TOL_MIN = 40  # 判定時刻±この分内のスナップだけ採用


def _cfg_of(sport_key: str) -> dict:
    for s in config.SPORTS:
        if s["sport_key"] == sport_key:
            return s
    return {}


def _nearest_snapshot(session, sport, game_id, team, point, jst_date, target):
    day_start = datetime.fromisoformat(f"{jst_date} 00:00:00")
    day_end = datetime.fromisoformat(f"{jst_date} 23:59:59")
    rows = session.execute(
        select(OddsSnapshot.snapshot_time, OddsSnapshot.odds_decimal).where(
            OddsSnapshot.sport == sport,
            OddsSnapshot.market == "spreads",
            OddsSnapshot.bookmaker == BOOK,
            OddsSnapshot.game_id == game_id,
            OddsSnapshot.team == team,
            OddsSnapshot.point == point,
            OddsSnapshot.snapshot_time >= day_start,
            OddsSnapshot.snapshot_time <= day_end,
        )
    ).all()
    if not rows:
        return None
    best = min(rows, key=lambda r: abs(r[0] - target))
    if abs(best[0] - target) > timedelta(minutes=TOL_MIN):
        return None
    return float(best[1])


def backfill_records(session, sport) -> int:
    """base_odds×snapshots から縮んだ側を paper_bets に記録。件数を返す。"""
    ch, cm = config.sport_check_time(_cfg_of(sport))
    base_rows = session.execute(
        select(BaseOdds).where(
            BaseOdds.sport == sport,
            BaseOdds.market == "spreads",
            BaseOdds.bookmaker == BOOK,
        )
    ).scalars().all()

    inserted = 0
    for b in base_rows:
        if b.point is None:
            continue
        jst_date = b.base_date.isoformat()
        target = datetime.fromisoformat(f"{jst_date} {ch:02d}:{cm:02d}:00")
        v = _nearest_snapshot(session, sport, b.game_id, b.team, b.point, jst_date, target)
        if v is None:
            continue
        move = round(v - float(b.base_odds_decimal), 2)
        if move > -config.LEVEL1:
            continue
        exists = session.execute(
            select(PaperBet.id).where(
                PaperBet.sport == sport, PaperBet.bet_date == b.base_date,
                PaperBet.game_id == b.game_id, PaperBet.team == b.team,
            ).limit(1)
        ).first()
        if exists:
            continue
        session.add(PaperBet(
            sport=sport, bet_date=b.base_date, game_id=b.game_id,
            game_name=b.game_name, team=b.team, point=b.point,
            entry_odds=b.base_odds_decimal, check_odds=Decimal(str(v)),
            move=Decimal(str(move)), commence_time=b.commence_time, settled=0,
        ))
        inserted += 1
    return inserted


def _us_date(commence_naive_utc: datetime) -> str:
    return (commence_naive_utc - timedelta(hours=4)).date().isoformat()


def settle_mlb(session) -> int:
    """未決済MLBベットを MLB Stats API(日付・チーム名)で決済。"""
    bets = session.execute(
        select(PaperBet).where(PaperBet.settled == 0, PaperBet.sport == "baseball_mlb")
    ).scalars().all()
    if not bets:
        return 0
    dates = sorted({_us_date(b.commence_time) for b in bets})
    sched = {}
    for d in dates:
        for g in get_schedule(d):
            sched[(d, g["away_team"], g["home_team"])] = (
                g["home_score"], g["away_score"], g["status"])
    results = {}
    for b in bets:
        away, _, home = b.game_name.partition(" vs ")
        d = _us_date(b.commence_time)
        r = sched.get((d, away, home))
        if r is None:  # 日付ズレ救済
            for k in (-1, 1):
                dd = (datetime.fromisoformat(d) + timedelta(days=k)).date().isoformat()
                r = sched.get((dd, away, home))
                if r:
                    break
        if r and r[2] == "Final" and r[0] is not None and r[1] is not None:
            results[b.game_id] = (r[0], r[1])
    return settle_paper_bets(session, results, sport="baseball_mlb")


def settle_soccer(session, sport) -> int:
    """未決済サッカーベットを /scores(直近3日)で決済。"""
    lookup = scores_lookup_from_oddsapi(get_scores(sport))
    return settle_paper_bets(session, lookup, sport=sport)


def run_backfill() -> str:
    """記録＋決済をまとめて実行し、要約文字列を返す。"""
    init_db()
    soccer = [k for k, _ in config._SOCCER_LEAGUES]
    with get_session() as s:
        rec = 0
        for sp in ["baseball_mlb"] + soccer:
            rec += backfill_records(s, sp)
        s.flush()
        settled = settle_mlb(s)
        for sp in soccer:
            settled += settle_soccer(s, sp)
    return f"バックフィル: 記録 {rec}件 / 決済 {settled}件"
