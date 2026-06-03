"""odds_utils のテスト。"""

from src.utils.odds_utils import american_to_decimal, decimal_to_american


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
