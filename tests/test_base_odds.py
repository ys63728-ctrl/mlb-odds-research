"""base_odds.py のテスト（in-memory DB を使用）。"""

from datetime import date

from sqlalchemy import select

from src.db.models import BaseOdds
from src.monitor.base_odds import (
    create_base_odds,
    create_base_odds_for_game,
    has_base_odds_for_date,
    has_base_odds_for_game,
    load_base_odds_map,
)
from tests._factories import make_game, make_bookmaker, make_outcome


BASE_DATE = date(2026, 5, 28)


def _two_book_game(game_id="g1"):
    """24時間以内に始まる試合 ＋ 2ブック分のオッズ。"""
    return make_game(
        game_id=game_id,
        away="Yankees",
        home="Red Sox",
        commence_time_iso="2026-05-28T15:00:00Z",  # fixed_now_utc(12:00)から3時間後
        bookmakers=[
            make_bookmaker("Pinnacle", [
                make_outcome("Yankees", -150),
                make_outcome("Red Sox", 130),
            ]),
            make_bookmaker("William Hill", [
                make_outcome("Yankees", -140),
                make_outcome("Red Sox", 125),
            ]),
        ],
    )


def test_create_base_odds_saves_all_books_and_outcomes(session, fixed_now_utc):
    games = [_two_book_game()]
    saved = create_base_odds(session, games, BASE_DATE, now_utc_override=fixed_now_utc)
    session.commit()

    # 2ブック × 2アウトカム = 4行
    assert saved == 4
    rows = session.execute(select(BaseOdds)).scalars().all()
    assert len(rows) == 4
    books = sorted({r.bookmaker for r in rows})
    assert books == ["Pinnacle", "William Hill"]


def test_create_base_odds_skips_games_outside_24h(session, fixed_now_utc):
    far_game = make_game(
        "g_far", "A", "B",
        "2026-05-30T12:00:00Z",  # 48時間後
        [make_bookmaker("Pinnacle", [
            make_outcome("A", -100),
            make_outcome("B", 100),
        ])],
    )
    saved = create_base_odds(session, [far_game], BASE_DATE, now_utc_override=fixed_now_utc)
    session.commit()

    assert saved == 0


def test_has_base_odds_for_date_false_when_empty(session):
    assert has_base_odds_for_date(session, BASE_DATE) is False


def test_has_base_odds_for_date_true_after_create(session, fixed_now_utc):
    create_base_odds(session, [_two_book_game()], BASE_DATE, now_utc_override=fixed_now_utc)
    session.commit()
    assert has_base_odds_for_date(session, BASE_DATE) is True


def test_load_base_odds_map_returns_correct_values(session, fixed_now_utc):
    create_base_odds(session, [_two_book_game()], BASE_DATE, now_utc_override=fixed_now_utc)
    session.commit()

    m = load_base_odds_map(session, BASE_DATE)

    # American -150 → Decimal 1.67、+130 → 2.30
    assert m[("g1", "Pinnacle", "Yankees")] == 1.67
    assert m[("g1", "Pinnacle", "Red Sox")] == 2.30
    assert m[("g1", "William Hill", "Yankees")] == 1.71  # -140 → 1.71
    assert m[("g1", "William Hill", "Red Sox")] == 2.25  # +125 → 2.25


# --- 試合ごと方式（NPB） ---
NPB = "baseball_npb"


def test_create_base_odds_for_game_saves_ignoring_24h(session):
    """試合ごと保存は24時間フィルタを掛けず、その試合の全ブックを保存する。"""
    # わざと48時間後の試合にする（固定時刻方式ならスキップされる時刻）
    game = make_game(
        "npb1", "Hanshin Tigers", "Yomiuri Giants",
        "2026-05-30T09:00:00Z",
        [make_bookmaker("Pinnacle", [
            make_outcome("Hanshin Tigers", -150),
            make_outcome("Yomiuri Giants", 130),
        ])],
    )
    saved = create_base_odds_for_game(session, game, BASE_DATE, sport=NPB)
    session.commit()

    # 1ブック × 2アウトカム = 2行（24時間外でも保存される）
    assert saved == 2
    rows = session.execute(select(BaseOdds)).scalars().all()
    assert len(rows) == 2
    assert {r.sport for r in rows} == {NPB}


def test_has_base_odds_for_game_tracks_per_game(session):
    game = make_game(
        "npb1", "Hanshin Tigers", "Yomiuri Giants",
        "2026-05-30T09:00:00Z",
        [make_bookmaker("Pinnacle", [make_outcome("Hanshin Tigers", -150)])],
    )
    assert has_base_odds_for_game(session, "npb1", sport=NPB) is False

    create_base_odds_for_game(session, game, BASE_DATE, sport=NPB)
    session.commit()

    assert has_base_odds_for_game(session, "npb1", sport=NPB) is True
    # 別の試合IDはまだ未保存
    assert has_base_odds_for_game(session, "npb2", sport=NPB) is False


def test_load_base_odds_map_is_sport_scoped(session, fixed_now_utc):
    """同じ日でも sport が違えば混ざらない。"""
    # MLB（固定時刻方式）の基準
    create_base_odds(session, [_two_book_game("mlbX")], BASE_DATE, now_utc_override=fixed_now_utc)
    # NPB（試合ごと方式）の基準
    npb_game = make_game(
        "npbX", "Hanshin Tigers", "Yomiuri Giants",
        "2026-05-28T15:00:00Z",
        [make_bookmaker("Pinnacle", [make_outcome("Hanshin Tigers", -150)])],
    )
    create_base_odds_for_game(session, npb_game, BASE_DATE, sport=NPB)
    session.commit()

    mlb_map = load_base_odds_map(session, BASE_DATE)  # 省略時は config.SPORT_KEY(=MLB)
    npb_map = load_base_odds_map(session, BASE_DATE, sport=NPB)

    assert ("mlbX", "Pinnacle", "Yankees") in mlb_map
    assert ("npbX", "Pinnacle", "Hanshin Tigers") not in mlb_map
    assert ("npbX", "Pinnacle", "Hanshin Tigers") in npb_map
    assert ("mlbX", "Pinnacle", "Yankees") not in npb_map
