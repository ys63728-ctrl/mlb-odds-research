"""odds_utils のテスト。"""

from src.utils.odds_utils import (
    american_to_decimal,
    decimal_to_american,
    pick_balanced_line,
)


def test_american_positive_to_decimal():
    # +150 は「100賭けて150勝つ」→ 元本込みで2.50倍
    assert american_to_decimal(150) == 2.50


def test_american_negative_to_decimal():
    # -200 は「200賭けて100勝つ」→ 元本込みで1.50倍
    assert american_to_decimal(-200) == 1.50


def test_american_plus100_is_decimal_2():
    # 五分五分(+100)はちょうど2.00倍
    assert american_to_decimal(100) == 2.00


def test_decimal_to_american_favorite():
    # 1.50倍 は -200 に戻る
    assert decimal_to_american(1.50) == -200


def test_decimal_to_american_underdog():
    # 2.50倍 は +150 に戻る
    assert decimal_to_american(2.50) == 150


# --- pick_balanced_line (1.9ライン選択) ---
def _ladder():
    """マーリンズ vs パイレーツ風のハンデ階段（アメリカンオッズ）。"""
    return [
        {"name": "Marlins", "point": 1.5, "price": -162},   # 1.62
        {"name": "Marlins", "point": 1.0, "price": -110},   # 1.91 ← 1.95に最も近い
        {"name": "Marlins", "point": 2.0, "price": -227},   # 1.44
        {"name": "Marlins", "point": -1.5, "price": 215},   # 3.15
        {"name": "Pirates", "point": -1.0, "price": -102},  # 1.98 ← 1.95に最も近い
        {"name": "Pirates", "point": -1.5, "price": 145},   # 2.45
    ]


def test_pick_balanced_line_selects_point_nearest_1_95():
    res = pick_balanced_line(_ladder())
    assert res["Marlins"]["point"] == 1.0
    assert res["Marlins"]["odds_decimal"] == 1.91
    assert res["Pirates"]["point"] == -1.0
    assert res["Pirates"]["odds_decimal"] == 1.98


def test_pick_balanced_line_skips_incomplete_and_handles_empty():
    assert pick_balanced_line([]) == {}
    # point や price が欠けた要素は無視される
    partial = [
        {"name": "A", "point": None, "price": -110},
        {"name": "A", "price": -110},
        {"name": "A", "point": 1.0, "price": 100},  # 2.00 のみ有効
    ]
    res = pick_balanced_line(partial)
    assert res == {"A": {"point": 1.0, "odds_decimal": 2.00}}
