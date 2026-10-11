"""ハンデ速報コアロジックのテスト。"""

from datetime import datetime

from src import config
from src.monitor.handicap_report import (
    kickoff_in_window, pick_due_slot, extract_pinnacle_spread,
)


def _jst(h, m=0):
    return datetime(2026, 10, 11, h, m, tzinfo=config.JST)


# ---------- キックオフ窓(20:00〜翌1:30) ----------
def test_kickoff_window_includes_evening_and_after_midnight():
    assert kickoff_in_window(_jst(20, 0)) is True
    assert kickoff_in_window(_jst(22, 0)) is True
    assert kickoff_in_window(_jst(1, 30)) is True      # 境界(翌1:30)
    assert kickoff_in_window(datetime(2026, 10, 12, 0, 30, tzinfo=config.JST)) is True


def test_kickoff_window_excludes_out_of_range():
    assert kickoff_in_window(_jst(19, 59)) is False
    assert kickoff_in_window(_jst(1, 31)) is False     # 1:30超
    assert kickoff_in_window(_jst(12, 0)) is False


# ---------- 発火スロット ----------
def test_slot_fires_at_30_min():
    fire, marks = pick_due_slot(30.0, set())
    assert fire == 30 and 30 in marks


def test_slot_early_tolerance_31min():
    # 31分前でも早め収集でスロット30が発火可
    fire, _ = pick_due_slot(31.0, set())
    assert fire == 30


def test_slot_not_fire_too_early():
    # 32分前はまだ早い
    fire, _ = pick_due_slot(32.0, set())
    assert fire is None


def test_slot_skips_overdue_to_nearest():
    # bot復帰で12分前。30/25/20/15は取りこぼし→最も近い15を発火、overdueも済み扱い
    fire, marks = pick_due_slot(12.0, set())
    assert fire == 15
    assert set(marks) >= {30, 25, 20, 15}


def test_slot_not_refire_already_fired():
    fire, _ = pick_due_slot(10.0, {30, 25, 20, 15, 10})
    assert fire is None            # 10は発火済み、次は5(まだm>6)
    fire2, _ = pick_due_slot(5.0, {30, 25, 20, 15, 10})
    assert fire2 == 5


def test_slot_late_guard():
    # 2分前は遅すぎ(late_guard=3)→発火しない
    fire, _ = pick_due_slot(2.0, set())
    assert fire is None


# ---------- Pinnacleハンデ抽出 ----------
def test_extract_pinnacle_spread():
    game = {"bookmakers": [{"title": "Pinnacle", "markets": [{"key": "spreads", "outcomes": [
        {"name": "Crystal Palace", "point": 0, "price": 114},   # 2.14
        {"name": "Nottingham Forest", "point": 0, "price": -123},  # 1.81
    ]}]}]}
    out = extract_pinnacle_spread(game)
    teams = {t: (p, d) for t, p, d in out}
    assert teams["Crystal Palace"] == (0, 2.14)
    assert teams["Nottingham Forest"][1] == 1.81


def test_extract_returns_empty_without_pinnacle():
    game = {"bookmakers": [{"title": "DraftKings", "markets": [{"key": "spreads", "outcomes": []}]}]}
    assert extract_pinnacle_spread(game) == []
