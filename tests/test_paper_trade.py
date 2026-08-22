"""paper_trade.py（記録・決済・集計）のテスト。"""

from datetime import date, datetime

from sqlalchemy import select

from src import config
from src.db.models import PaperBet
from src.monitor.paper_trade import (
    record_paper_bets,
    settle_paper_bets,
    scores_lookup_from_oddsapi,
    summary,
)

BET_DATE = date(2026, 8, 22)
CHECK_TIME = datetime(2026, 8, 22, 23, 30)


def _handicap_game(marlins_point, marlins_price, pirates_point, pirates_price):
    """Pinnacle の alternate_spreads を持つ試合 'Marlins vs Pirates'。"""
    return {
        "id": "g1",
        "away_team": "Marlins",
        "home_team": "Pirates",
        "commence_time": "2026-08-23T00:00:00Z",
        "bookmakers": [{
            "title": "Pinnacle",
            "markets": [{"key": "alternate_spreads", "outcomes": [
                {"name": "Marlins", "point": marlins_point, "price": marlins_price},
                {"name": "Pirates", "point": pirates_point, "price": pirates_price},
            ]}],
        }],
    }


def _base(entry_marlins, entry_pirates):
    base_map = {
        ("g1", "Pinnacle", "Marlins"): entry_marlins,
        ("g1", "Pinnacle", "Pirates"): entry_pirates,
    }
    base_points = {
        ("g1", "Pinnacle", "Marlins"): 1.0,
        ("g1", "Pinnacle", "Pirates"): -1.0,
    }
    return base_map, base_points


# ---------- 記録 ----------
def test_records_only_shortened_side(session):
    # Marlins +1.0: 基準1.92 → 現在1.83(-120)=-0.09 縮んだ → 記録
    # Pirates -1.0: 基準2.00 → 現在2.05(+105)=+0.05 伸びた → 記録しない
    game = _handicap_game(1.0, -120, -1.0, 105)
    base_map, base_points = _base(1.92, 2.00)
    n = record_paper_bets(
        session, [game], base_map, base_points,
        sport="baseball_mlb", bet_date=BET_DATE, check_time=CHECK_TIME,
    )
    session.commit()
    assert n == 1
    rows = session.execute(select(PaperBet)).scalars().all()
    assert len(rows) == 1
    assert rows[0].team == "Marlins"
    assert float(rows[0].entry_odds) == 1.92
    assert float(rows[0].move) == -0.09


def test_record_is_idempotent(session):
    game = _handicap_game(1.0, -120, -1.0, 105)
    base_map, base_points = _base(1.92, 2.00)
    kw = dict(sport="baseball_mlb", bet_date=BET_DATE, check_time=CHECK_TIME)
    record_paper_bets(session, [game], base_map, base_points, **kw)
    session.commit()
    n2 = record_paper_bets(session, [game], base_map, base_points, **kw)
    session.commit()
    assert n2 == 0
    assert len(session.execute(select(PaperBet)).scalars().all()) == 1


def test_no_record_when_not_shortened(session):
    # 両サイドとも動かない → 記録なし
    game = _handicap_game(1.0, -110, -1.0, -110)  # 1.91 / 1.91
    base_map, base_points = _base(1.91, 1.91)
    n = record_paper_bets(
        session, [game], base_map, base_points,
        sport="baseball_mlb", bet_date=BET_DATE, check_time=CHECK_TIME,
    )
    assert n == 0


# ---------- 決済 ----------
def test_settle_win_updates_pt(session):
    game = _handicap_game(1.0, -120, -1.0, 105)
    base_map, base_points = _base(1.92, 2.00)
    record_paper_bets(
        session, [game], base_map, base_points,
        sport="baseball_mlb", bet_date=BET_DATE, check_time=CHECK_TIME,
    )
    session.commit()
    # Marlins(+1.0, away) が 3-1 で勝ち → margin +2, adj +3 → win, +0.92
    n = settle_paper_bets(session, {"g1": (1, 3)}, sport="baseball_mlb")  # (home, away)
    session.commit()
    assert n == 1
    bet = session.execute(select(PaperBet)).scalars().one()
    assert bet.settled == 1
    assert bet.result == "win"
    assert float(bet.pt) == 0.92
    assert bet.home_score == 1 and bet.away_score == 3


def test_settle_skips_unknown_game(session):
    game = _handicap_game(1.0, -120, -1.0, 105)
    base_map, base_points = _base(1.92, 2.00)
    record_paper_bets(
        session, [game], base_map, base_points,
        sport="baseball_mlb", bet_date=BET_DATE, check_time=CHECK_TIME,
    )
    session.commit()
    n = settle_paper_bets(session, {"other": (2, 1)}, sport="baseball_mlb")
    assert n == 0


# ---------- /scores パース ----------
def test_scores_lookup_parses_completed_only():
    scores = [
        {"id": "a", "completed": True, "home_team": "H", "away_team": "A",
         "scores": [{"name": "H", "score": "2"}, {"name": "A", "score": "1"}]},
        {"id": "b", "completed": False, "home_team": "H2", "away_team": "A2",
         "scores": None},
    ]
    out = scores_lookup_from_oddsapi(scores)
    assert out == {"a": (2, 1)}


# ---------- 集計 ----------
def test_summary_aggregates(session):
    game = _handicap_game(1.0, -120, -1.0, 105)
    base_map, base_points = _base(1.92, 2.00)
    record_paper_bets(
        session, [game], base_map, base_points,
        sport="baseball_mlb", bet_date=BET_DATE, check_time=CHECK_TIME,
    )
    session.commit()
    settle_paper_bets(session, {"g1": (1, 3)}, sport="baseball_mlb")
    session.commit()
    s = summary(session, sport="baseball_mlb")
    assert s["bets"] == 1
    assert s["win"] == 1
    assert s["total_pt"] == 0.92
    assert s["hit_rate"] == 100.0
