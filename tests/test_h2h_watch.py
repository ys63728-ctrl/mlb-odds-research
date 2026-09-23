"""1×2(h2h)人気側監視のテスト。"""

from datetime import date, datetime

from src import config
from src.monitor.base_odds import create_h2h_favorite_base_for_game, load_h2h_base_map
from src.monitor.level_check import MonitorState, evaluate
from src.utils.odds_utils import pick_h2h_favorite
from tests._factories import make_game, make_bookmaker, make_outcome

BASE_DATE = date(2026, 9, 24)
ALERT = datetime(2026, 9, 24, 18, 0, tzinfo=config.JST)
COMMENCE = "2026-09-24T09:00:00Z"


def _pinn_h2h(yankees_price, redsox_price):
    return make_game(
        "g1", "Yankees", "Red Sox", COMMENCE,
        [make_bookmaker("Pinnacle", [
            make_outcome("Yankees", yankees_price),
            make_outcome("Red Sox", redsox_price),
        ])],
    )


# ---------- 人気側の選択 ----------
def test_pick_favorite_smallest_odds():
    outs = [{"name": "Yankees", "price": -150}, {"name": "Red Sox", "price": 130}]
    assert pick_h2h_favorite(outs)["team"] == "Yankees"


def test_pick_favorite_excludes_draw():
    # サッカー3-way。Draw除外し、最小オッズのHomeが人気側
    outs = [{"name": "Home", "price": 120}, {"name": "Draw", "price": 240},
            {"name": "Away", "price": 200}]
    fav = pick_h2h_favorite(outs)
    assert fav["team"] == "Home"
    assert fav["odds_decimal"] == 2.20


# ---------- 基準保存＝人気側1つだけ ----------
def test_base_saves_only_favorite(session):
    # Yankees -182(=1.55) が人気側 / Red Sox +150(=2.50)
    n = create_h2h_favorite_base_for_game(
        session, _pinn_h2h(-182, 150), BASE_DATE, sport="baseball_npb")
    session.commit()
    assert n == 1
    m = load_h2h_base_map(session, BASE_DATE, sport="baseball_npb")
    assert m == {("g1", "Pinnacle", "Yankees"): 1.55}   # 人気側のみ


# ---------- 人気側が0.05動いたら通知 ----------
def test_favorite_move_fires(session):
    create_h2h_favorite_base_for_game(session, _pinn_h2h(-182, 150), BASE_DATE, sport="baseball_npb")
    session.commit()
    m = load_h2h_base_map(session, BASE_DATE, sport="baseball_npb")
    # 現在: Yankees -167(=1.60) → +0.05 → Level1 / Red Sox +140(=2.40)
    cur = _pinn_h2h(-167, 140)
    ev = evaluate(session, [cur], m, MonitorState(),
                  alert_time=ALERT, sport="baseball_npb", base_points=None)
    pinn = [e for e in ev if e.kind == "pinnacle_level"]
    assert len(pinn) == 1
    assert pinn[0].team == "Yankees"
    assert pinn[0].level == 1


# ---------- 人気薄だけ動いても無視 ----------
def test_underdog_only_move_ignored(session):
    create_h2h_favorite_base_for_game(session, _pinn_h2h(-182, 150), BASE_DATE, sport="baseball_npb")
    session.commit()
    m = load_h2h_base_map(session, BASE_DATE, sport="baseball_npb")
    # Yankees据え置き -182(=1.55) / Red Sox +170(=2.70, 2.50→2.70で+0.20動くが対象外)
    cur = _pinn_h2h(-182, 170)
    ev = evaluate(session, [cur], m, MonitorState(),
                  alert_time=ALERT, sport="baseball_npb", base_points=None)
    assert [e for e in ev if e.kind == "pinnacle_level"] == []
