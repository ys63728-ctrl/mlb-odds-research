"""snapshot.py のテスト。"""

from datetime import datetime

from sqlalchemy import select

from src import config
from src.db.models import OddsSnapshot
from src.monitor.snapshot import save_snapshot
from tests._factories import make_game, make_bookmaker, make_outcome


def _snap_time():
    """JST 21:05 の固定スナップショット時刻。"""
    return datetime(2026, 5, 28, 21, 5, tzinfo=config.JST)


def test_save_snapshot_saves_all_books_within_24h(session, fixed_now_utc):
    games = [
        make_game(
            "g1", "Yankees", "Red Sox",
            "2026-05-28T15:00:00Z",
            [
                make_bookmaker("Pinnacle", [
                    make_outcome("Yankees", -150),
                    make_outcome("Red Sox", 130),
                ]),
                make_bookmaker("BetOnline.ag", [
                    make_outcome("Yankees", -145),
                    make_outcome("Red Sox", 128),
                ]),
            ],
        )
    ]
    saved = save_snapshot(session, games, _snap_time(), now_utc_override=fixed_now_utc)
    session.commit()

    assert saved == 4
    rows = session.execute(select(OddsSnapshot)).scalars().all()
    assert len(rows) == 4


def test_save_snapshot_skips_games_outside_24h(session, fixed_now_utc):
    far_game = make_game(
        "g_far", "A", "B",
        "2026-05-30T12:00:00Z",  # 48時間後
        [make_bookmaker("Pinnacle", [
            make_outcome("A", -100),
            make_outcome("B", 100),
        ])],
    )
    saved = save_snapshot(session, [far_game], _snap_time(), now_utc_override=fixed_now_utc)
    session.commit()
    assert saved == 0


def test_save_snapshot_stores_decimal_and_american_correctly(session, fixed_now_utc):
    games = [
        make_game(
            "g1", "A", "B",
            "2026-05-28T15:00:00Z",
            [make_bookmaker("Pinnacle", [
                make_outcome("A", -150),  # → 1.67
                make_outcome("B", 130),   # → 2.30
            ])],
        )
    ]
    save_snapshot(session, games, _snap_time(), now_utc_override=fixed_now_utc)
    session.commit()

    rows = (
        session.execute(
            select(OddsSnapshot).order_by(OddsSnapshot.team)
        )
        .scalars()
        .all()
    )
    by_team = {r.team: r for r in rows}

    assert float(by_team["A"].odds_decimal) == 1.67
    assert by_team["A"].odds_american == -150
    assert float(by_team["B"].odds_decimal) == 2.30
    assert by_team["B"].odds_american == 130
    # point は h2h なので None のまま
    assert by_team["A"].point is None


def test_save_snapshot_keeps_sport_label(session, fixed_now_utc):
    games = [
        make_game("g1", "A", "B", "2026-05-28T15:00:00Z",
                  [make_bookmaker("Pinnacle", [make_outcome("A", -100), make_outcome("B", 100)])])
    ]
    save_snapshot(session, games, _snap_time(), now_utc_override=fixed_now_utc)
    session.commit()

    rows = session.execute(select(OddsSnapshot)).scalars().all()
    assert all(r.sport == config.SPORT_KEY for r in rows)
