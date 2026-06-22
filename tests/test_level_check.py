"""level_check.py のテスト（判定の脳みそ）。"""

from datetime import datetime
from sqlalchemy import select

from src import config
from src.db.models import Alert
from src.monitor.level_check import (
    MonitorState,
    NotificationEvent,
    evaluate,
    get_level,
)
from tests._factories import make_game, make_bookmaker, make_outcome


ALERT_TIME = datetime(2026, 5, 28, 21, 5, tzinfo=config.JST)


# =====================================================================
# get_level の単体テスト
# =====================================================================
def test_get_level_zero_when_small():
    assert get_level(0.04) == 0


def test_get_level_one_at_threshold():
    assert get_level(0.05) == 1
    assert get_level(-0.05) == 1


def test_get_level_two_at_higher_threshold():
    assert get_level(0.075) == 2
    assert get_level(-0.08) == 2


def test_get_level_three_at_threshold():
    assert get_level(0.10) == 3
    assert get_level(-0.12) == 3   # 0.10〜0.125 の間は Level3


def test_get_level_four_to_seven():
    assert get_level(0.125) == 4
    assert get_level(-0.125) == 4
    assert get_level(0.15) == 5
    assert get_level(0.175) == 6
    assert get_level(0.20) == 7
    # 中間値は下のレベルにとどまる
    assert get_level(0.149) == 4
    assert get_level(0.199) == 6


def test_get_level_seven_is_max_even_for_bigger_moves():
    # 0.20 を超えても最大は Level7（現状の最上位）
    assert get_level(0.35) == 7
    assert get_level(-0.50) == 7


# =====================================================================
# ヘルパー：1ブック1チームの「現在オッズ」を作る
# =====================================================================
def _game_with_books(books_team_prices: list[tuple[str, list[tuple[str, int]]]]):
    """
    例: [("Pinnacle", [("Yankees", -150), ("Red Sox", 130)]), ...]
    """
    return make_game(
        "g1", "Yankees", "Red Sox", "2026-05-28T15:00:00Z",
        [make_bookmaker(book, [make_outcome(t, p) for t, p in outs])
         for book, outs in books_team_prices],
    )


# =====================================================================
# A. Pinnacle 単体変動
# =====================================================================
def test_pinnacle_level1_fires_on_first_move(session):
    # 基準 1.50（Pinnacle, Yankees） → 現在 1.55（=+0.05 ちょうど）
    games = [_game_with_books([("Pinnacle", [("Yankees", -182), ("Red Sox", 150)])])]
    # american_to_decimal: -182 → 1.55, +150 → 2.50
    base_map = {
        ("g1", "Pinnacle", "Yankees"): 1.50,
        ("g1", "Pinnacle", "Red Sox"): 2.50,
    }
    state = MonitorState()
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    session.commit()

    pinn_events = [e for e in events if e.kind == "pinnacle_level"]
    assert len(pinn_events) == 1
    assert pinn_events[0].team == "Yankees"
    assert pinn_events[0].level == 1
    assert pinn_events[0].move == 0.05
    # DBにも記録されている
    rows = session.execute(select(Alert).where(Alert.alert_type == "level1")).scalars().all()
    assert len(rows) == 1


def test_pinnacle_does_not_re_fire_on_same_level(session):
    games = [_game_with_books([("Pinnacle", [("Yankees", -182), ("Red Sox", 150)])])]
    base_map = {
        ("g1", "Pinnacle", "Yankees"): 1.50,
        ("g1", "Pinnacle", "Red Sox"): 2.50,
    }
    state = MonitorState()
    # 1回目: Level1 で発火
    evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    # 2回目: 同じ状態なので何も出ない
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    session.commit()
    assert events == []


def test_pinnacle_level_clear_fires_when_returns_to_zero(session):
    # Yankees だけ動かす（Red Sox は基準=現在で動かさない）
    # 1回目: Yankees 1.55 vs base 1.67 → -0.12 → Level3
    moved = [_game_with_books([("Pinnacle", [("Yankees", -182), ("Red Sox", 130)])])]
    # 2回目: Yankees 1.67 (基準と同じ) → Level0 → clear
    cleared = [_game_with_books([("Pinnacle", [("Yankees", -150), ("Red Sox", 130)])])]
    base_map = {
        ("g1", "Pinnacle", "Yankees"): 1.67,  # = decimal(-150)
        ("g1", "Pinnacle", "Red Sox"): 2.30,  # = decimal(+130) Red Soxは一切動かさない
    }
    state = MonitorState()
    evaluate(session, moved, base_map, state, alert_time=ALERT_TIME)  # Level3 発火
    events = evaluate(session, cleared, base_map, state, alert_time=ALERT_TIME)  # clear 発火
    session.commit()
    clears = [e for e in events if e.kind == "pinnacle_clear"]
    assert len(clears) == 1
    assert clears[0].team == "Yankees"


def test_non_pinnacle_book_does_not_trigger_pinnacle_alert(session):
    # William Hill だけ動かす → Pinnacle単体通知は出ない
    games = [_game_with_books([("William Hill", [("Yankees", -182), ("Red Sox", 150)])])]
    base_map = {
        ("g1", "William Hill", "Yankees"): 1.50,
        ("g1", "William Hill", "Red Sox"): 2.50,
    }
    state = MonitorState()
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    session.commit()
    assert [e for e in events if e.kind == "pinnacle_level"] == []


# =====================================================================
# B. Steam Move
# =====================================================================
def test_steam_fires_when_three_books_move_same_direction(session):
    """3ブックが同方向に下落（2.1倍以下）→ Steam(down) 発火"""
    # Red Sox 基準2.00 → 現在1.90（-0.10, 2.1倍以下）を3ブックで
    # american -111 → decimal 1.90
    games = [_game_with_books([
        ("Pinnacle",     [("Yankees", -200), ("Red Sox", -111)]),
        ("BetOnline.ag", [("Yankees", -200), ("Red Sox", -111)]),
        ("LowVig.ag",    [("Yankees", -200), ("Red Sox", -111)]),
    ])]
    base_map = {
        ("g1", "Pinnacle",     "Red Sox"): 2.00,
        ("g1", "BetOnline.ag", "Red Sox"): 2.00,
        ("g1", "LowVig.ag",    "Red Sox"): 2.00,
        ("g1", "Pinnacle",     "Yankees"): 1.50,
        ("g1", "BetOnline.ag", "Yankees"): 1.50,
        ("g1", "LowVig.ag",    "Yankees"): 1.50,
    }
    state = MonitorState()
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    session.commit()

    rs_steam = [e for e in events if e.kind == "steam_move" and e.team == "Red Sox"]
    assert len(rs_steam) == 1
    assert rs_steam[0].direction == "down"
    assert len(rs_steam[0].books) == 3


def test_steam_does_not_fire_with_only_two_books(session):
    """2ブックしか動かない → 3未満なので Steam は出ない。"""
    games = [_game_with_books([
        ("Pinnacle",     [("Yankees", -200), ("Red Sox", -111)]),  # 1.90 動いた
        ("BetOnline.ag", [("Yankees", -200), ("Red Sox", -111)]),  # 1.90 動いた
        ("LowVig.ag",    [("Yankees", -200), ("Red Sox", 100)]),   # 2.00 動かない
    ])]
    base_map = {
        ("g1", "Pinnacle",     "Red Sox"): 2.00,
        ("g1", "BetOnline.ag", "Red Sox"): 2.00,
        ("g1", "LowVig.ag",    "Red Sox"): 2.00,
        ("g1", "Pinnacle",     "Yankees"): 1.50,
        ("g1", "BetOnline.ag", "Yankees"): 1.50,
        ("g1", "LowVig.ag",    "Yankees"): 1.50,
    }
    state = MonitorState()
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    assert [e for e in events if e.kind == "steam_move" and e.team == "Red Sox"] == []


def test_steam_ignores_sides_above_2_1(session):
    """3ブック動いても 2.1倍より高いサイドは対象外で Steam は出ない。"""
    # Red Sox 基準2.40 → 現在2.25（>2.1）を3ブックで → 除外
    games = [_game_with_books([
        ("Pinnacle",     [("Yankees", -200), ("Red Sox", 125)]),  # 2.25
        ("BetOnline.ag", [("Yankees", -200), ("Red Sox", 125)]),
        ("LowVig.ag",    [("Yankees", -200), ("Red Sox", 125)]),
    ])]
    base_map = {("g1", b, "Red Sox"): 2.40 for b in ["Pinnacle", "BetOnline.ag", "LowVig.ag"]}
    base_map.update({("g1", b, "Yankees"): 1.50 for b in ["Pinnacle", "BetOnline.ag", "LowVig.ag"]})
    state = MonitorState()
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    assert [e for e in events if e.kind == "steam_move" and e.team == "Red Sox"] == []


def test_steam_does_not_fire_on_opposite_directions(session):
    """Pinnacle 下落・BetOnline 上昇 → 方向が違うのでSteamは出ない"""
    games = [_game_with_books([
        # Red Sox: Pinnacle 2.40 (down), BetOnline 2.60 (up)
        ("Pinnacle",      [("Yankees", -200), ("Red Sox", 140)]),  # 2.40 down
        ("BetOnline.ag",  [("Yankees", -130), ("Red Sox", 160)]),  # 2.60 up
    ])]
    base_map = {
        ("g1", "Pinnacle",     "Yankees"): 1.50,
        ("g1", "Pinnacle",     "Red Sox"): 2.50,
        ("g1", "BetOnline.ag", "Yankees"): 1.50,
        ("g1", "BetOnline.ag", "Red Sox"): 2.50,
    }
    state = MonitorState()
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    session.commit()

    rs_steam = [e for e in events if e.kind == "steam_move" and e.team == "Red Sox"]
    assert rs_steam == []


def test_steam_does_not_re_fire_until_direction_changes(session):
    games = [_game_with_books([
        ("Pinnacle",      [("Yankees", -200), ("Red Sox", 140)]),
        ("BetOnline.ag",  [("Yankees", -195), ("Red Sox", 140)]),
    ])]
    base_map = {
        ("g1", "Pinnacle",     "Red Sox"): 2.50,
        ("g1", "BetOnline.ag", "Red Sox"): 2.50,
        ("g1", "Pinnacle",     "Yankees"): 1.67,
        ("g1", "BetOnline.ag", "Yankees"): 1.67,
    }
    state = MonitorState()
    # 1回目発火
    evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    # 2回目は同じ状態なので何も出ない
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    session.commit()
    assert [e for e in events if e.kind == "steam_move"] == []


def test_steam_clear_fires_when_no_longer_enough_books(session):
    # 3ブック下落で発火 → 基準に戻って解除
    moved = [_game_with_books([
        ("Pinnacle",     [("Yankees", -200), ("Red Sox", -111)]),
        ("BetOnline.ag", [("Yankees", -200), ("Red Sox", -111)]),
        ("LowVig.ag",    [("Yankees", -200), ("Red Sox", -111)]),
    ])]
    back = [_game_with_books([
        ("Pinnacle",     [("Yankees", -200), ("Red Sox", 100)]),
        ("BetOnline.ag", [("Yankees", -200), ("Red Sox", 100)]),
        ("LowVig.ag",    [("Yankees", -200), ("Red Sox", 100)]),
    ])]
    base_map = {
        ("g1", "Pinnacle",     "Red Sox"): 2.00,
        ("g1", "BetOnline.ag", "Red Sox"): 2.00,
        ("g1", "LowVig.ag",    "Red Sox"): 2.00,
        ("g1", "Pinnacle",     "Yankees"): 1.50,
        ("g1", "BetOnline.ag", "Yankees"): 1.50,
        ("g1", "LowVig.ag",    "Yankees"): 1.50,
    }
    state = MonitorState()
    evaluate(session, moved, base_map, state, alert_time=ALERT_TIME)   # 発火
    events = evaluate(session, back, base_map, state, alert_time=ALERT_TIME)  # 解除
    session.commit()
    clears = [e for e in events if e.kind == "steam_clear" and e.team == "Red Sox"]
    assert len(clears) >= 1


def test_steam_fires_even_without_pinnacle(session):
    """Pinnacleが動かなくても、3つの他ブックだけで Steam が出る。"""
    books = ["Pinnacle", "BetOnline.ag", "LowVig.ag", "MyBookie.ag"]
    games = [_game_with_books([
        ("Pinnacle",     [("Yankees", -200), ("Red Sox", 100)]),   # 2.00 動かない
        ("BetOnline.ag", [("Yankees", -200), ("Red Sox", -111)]),  # 1.90
        ("LowVig.ag",    [("Yankees", -200), ("Red Sox", -111)]),
        ("MyBookie.ag",  [("Yankees", -200), ("Red Sox", -111)]),
    ])]
    base_map = {("g1", b, "Red Sox"): 2.00 for b in books}
    base_map.update({("g1", b, "Yankees"): 1.50 for b in books})
    state = MonitorState()
    events = evaluate(session, games, base_map, state, alert_time=ALERT_TIME)
    session.commit()
    rs_steam = [e for e in events if e.kind == "steam_move" and e.team == "Red Sox"]
    assert len(rs_steam) == 1
    book_names = {b["bookmaker"] for b in rs_steam[0].books}
    assert "Pinnacle" not in book_names
    assert book_names == {"BetOnline.ag", "LowVig.ag", "MyBookie.ag"}


# =====================================================================
# C. ハンデ(handicap)モード: 基準pointの価格で判定する
# =====================================================================
def _handicap_game(marlins_point_1_0_price: int):
    """Pinnacle の alternate_spreads 階段を持つ試合。"""
    return {
        "id": "g1",
        "away_team": "Marlins",
        "home_team": "Pirates",
        "commence_time": "2026-05-28T15:00:00Z",
        "bookmakers": [{
            "title": "Pinnacle",
            "markets": [{"key": "alternate_spreads", "outcomes": [
                {"name": "Marlins", "point": 1.0, "price": marlins_point_1_0_price},
                {"name": "Marlins", "point": 1.5, "price": -160},
                {"name": "Pirates", "point": -1.0, "price": -105},
            ]}],
        }],
    }


def test_handicap_level_uses_base_point_price(session):
    """基準で選んだ point(+1.0) の現在価格だけで Level を判定する。"""
    # 基準: Marlins +1.0 @ 1.91 → 現在 +1.0 @ 1.80 (american -125) → 変動 -0.11 → LEVEL3
    games = [_handicap_game(-125)]
    base_map = {("g1", "Pinnacle", "Marlins"): 1.91}
    base_points = {("g1", "Pinnacle", "Marlins"): 1.0}
    state = MonitorState()
    events = evaluate(
        session, games, base_map, state,
        alert_time=ALERT_TIME, sport="baseball_mlb", base_points=base_points,
    )
    session.commit()
    pinn = [e for e in events if e.kind == "pinnacle_level" and e.team == "Marlins"]
    assert len(pinn) == 1
    assert pinn[0].level == 3
    assert pinn[0].point == 1.0
    assert pinn[0].current_odds == 1.80


def test_handicap_ignores_non_base_point(session):
    """基準pointと違うラインしか動いていなければ Level は出ない。"""
    # 基準 +1.0 @1.91。現在も +1.0 @1.91（-110）→ 動いていない
    games = [_handicap_game(-110)]
    base_map = {("g1", "Pinnacle", "Marlins"): 1.91}
    base_points = {("g1", "Pinnacle", "Marlins"): 1.0}
    state = MonitorState()
    events = evaluate(
        session, games, base_map, state,
        alert_time=ALERT_TIME, sport="baseball_mlb", base_points=base_points,
    )
    assert [e for e in events if e.kind == "pinnacle_level"] == []
