"""
ハンデ（アジアンハンデ含む）のカバー決済ロジック。

ペーパートレードの1ベット（対象チーム team・ライン point・エントリー倍率 entry_odds）を、
試合の最終スコアで決済し、(結果カテゴリ, 損益pt) を返す。

決済ルール:
  調整マージン adj = (対象チームの得失点差) + point
  - 整数/ハーフライン(例 -1.0, -1.5, 0, +0.5): adj>0=勝ち / adj==0=push / adj<0=負け
  - クォーターライン(例 -0.25, -0.75, +0.25): ステークを半分ずつ隣接2ライン
    (point-0.25 と point+0.25) に分け、それぞれ上の規則で決済して合算
    → 「半勝ち(half_win)」「半プッシュ(half_lose)」が発生する。

損益pt(1pt賭け):
  勝ち = entry_odds - 1 / push = 0 / 負け = -1
  半勝ち・半分けはその半分ずつ。
"""

from __future__ import annotations


def _is_quarter_line(point: float) -> bool:
    """クォーターライン(.25 / .75)なら True。整数・ハーフラインは False。"""
    return (round(point * 2, 6) % 1) != 0


def _settle_whole_or_half(adj: float) -> str:
    """整数/ハーフラインの1発判定。'win'/'push'/'lose'。"""
    if adj > 0:
        return "win"
    if adj == 0:
        return "push"
    return "lose"


def settle_handicap(
    *,
    team_is_home: bool,
    home_score: int,
    away_score: int,
    point: float,
    entry_odds: float,
) -> tuple[str, float]:
    """
    ハンデを決済して (result, pt) を返す。

    result: 'win' | 'lose' | 'push' | 'half_win' | 'half_lose'
    pt    : 損益（1pt賭け, 小数第2位で丸め）
    """
    point = float(point)
    entry = float(entry_odds)
    win_pt = round(entry - 1.0, 2)

    margin = (home_score - away_score) if team_is_home else (away_score - home_score)

    # --- 整数 / ハーフライン ---
    if not _is_quarter_line(point):
        res = _settle_whole_or_half(margin + point)
        if res == "win":
            return "win", win_pt
        if res == "push":
            return "push", 0.0
        return "lose", -1.0

    # --- クォーターライン: 隣接2ラインへ半分ずつ ---
    outs: list[str] = []
    pt = 0.0
    for line in (point - 0.25, point + 0.25):
        res = _settle_whole_or_half(margin + line)
        outs.append(res)
        if res == "win":
            pt += 0.5 * win_pt
        elif res == "lose":
            pt += -0.5
        # push は +0
    pt = round(pt, 2)

    if outs == ["win", "win"]:
        return "win", pt
    if outs == ["lose", "lose"]:
        return "lose", pt
    if "win" in outs:          # 片方勝ち・片方push
        return "half_win", pt
    return "half_lose", pt     # 片方負け・片方push
