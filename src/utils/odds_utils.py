"""
オッズの形式変換ユーティリティ。

アメリカン形式 ↔ デシマル形式の相互変換。
- アメリカン: +150, -200 のような正負の数。アメリカで主流。
- デシマル  : 2.50, 1.50 のような小数。ヨーロッパで主流。比較しやすい。
"""


def american_to_decimal(american: int | float) -> float:
    """
    アメリカン形式のオッズをデシマル形式に変換する。

    例:
        american_to_decimal(+150) -> 2.50
        american_to_decimal(-200) -> 1.50
    """
    if american > 0:
        return round(american / 100 + 1, 2)
    return round(100 / abs(american) + 1, 2)


def decimal_to_american(decimal: float) -> int:
    """
    デシマル形式のオッズをアメリカン形式に変換する。
    （Phase1では使わないが、将来の表示用に用意）
    """
    if decimal >= 2.0:
        return round((decimal - 1) * 100)
    return round(-100 / (decimal - 1))
