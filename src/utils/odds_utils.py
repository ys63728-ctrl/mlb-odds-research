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


def pick_balanced_line(
    outcomes: list[dict],
    target_decimal: float = 1.95,
) -> dict[str, dict]:
    """
    1ブックの alternate_spreads(ハンデ階段) の outcomes から、各チームについて
    「デシマル価格が target_decimal(=1.95, つまり1.9〜2.0の真ん中) に最も近い point」
    を選ぶ。これが『基準にする1.9ライン』になる。

    Args:
        outcomes: [{"name": チーム名, "point": ハンデ, "price": アメリカンオッズ}, ...]
        target_decimal: 狙うデシマル価格（1.9前後の中心）

    Returns:
        {チーム名: {"point": float, "odds_decimal": float}}
        該当が無いチームは含まれない。
    """
    best: dict[str, dict] = {}
    for o in outcomes:
        name = o.get("name")
        point = o.get("point")
        price = o.get("price")
        if name is None or point is None or price is None:
            continue
        dec = american_to_decimal(price)
        diff = abs(dec - target_decimal)
        cur = best.get(name)
        if cur is None or diff < cur["_diff"]:
            best[name] = {"point": float(point), "odds_decimal": dec, "_diff": diff}

    for v in best.values():
        v.pop("_diff", None)
    return best


def decimal_to_american(decimal: float) -> int:
    """
    デシマル形式のオッズをアメリカン形式に変換する。
    （Phase1では使わないが、将来の表示用に用意）
    """
    if decimal >= 2.0:
        return round((decimal - 1) * 100)
    return round(-100 / (decimal - 1))
