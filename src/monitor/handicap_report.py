"""
ハンデ速報（サッカー）のコアロジック（純関数）。

対応サッカー全大会で、JST 20:00〜翌1:30 に始まる試合について、
開始30分前〜5分前に5分おき（計6回）Pinnacleのメインハンデ倍率を通知する。
ここでは「対象キックオフか」「今どのスロットを発火すべきか」「ハンデ抽出」だけを担い、
取得・送信・状態管理は discord_bot 側が行う。
"""

from datetime import datetime

from src import config
from src.utils.odds_utils import american_to_decimal


def kickoff_in_window(
    commence_jst: datetime,
    start_hm: tuple[int, int] = config.HANDICAP_REPORT_KICKOFF_START,
    end_hm: tuple[int, int] = config.HANDICAP_REPORT_KICKOFF_END,
) -> bool:
    """キックオフ(JST)が対象時間帯(既定 20:00〜翌1:30)に入るか。日跨ぎ対応。"""
    cur = commence_jst.hour * 60 + commence_jst.minute
    start = start_hm[0] * 60 + start_hm[1]
    end = end_hm[0] * 60 + end_hm[1]
    if start <= end:
        return start <= cur <= end
    return cur >= start or cur <= end


def pick_due_slot(
    minutes_before: float,
    fired: set[int],
    slots: list[int] = None,
    early_tol: int = 1,
    late_guard: int = 3,
):
    """
    今発火すべきスロット（開始何分前の通知か）を決める。

    Args:
        minutes_before: キックオフまでの残り分
        fired: この試合で既に発火/スキップ済みのスロット集合
        early_tol: スロット時刻の何分前から発火可とするか（収集を少し早める許容）
        late_guard: 残りこの分未満なら発火しない（遅すぎる取りこぼし防止）

    Returns:
        (fire_slot, marks)
        fire_slot: 今回発火するスロット(分) / 無ければ None
        marks: 発火成功時に「済み」にすべきスロット一覧（overdueな大きいスロットも含む）
    """
    if slots is None:
        slots = config.HANDICAP_REPORT_SLOTS
    if minutes_before < late_guard:
        return None, []
    due = [t for t in slots if minutes_before <= t + early_tol and t not in fired]
    if not due:
        return None, []
    # キックオフに最も近い(最小の)スロットを発火。取りこぼした大きいスロットは一緒に済み扱い。
    return min(due), due


def extract_pinnacle_spread(game: dict, book: str = config.PRIMARY_BOOKMAKER):
    """
    bulk /odds(markets='spreads') の game から、Pinnacleのメインハンデを
    [(team, point, decimal), ...] で返す。無ければ空リスト。
    """
    if not isinstance(game, dict):
        return []
    for b in game.get("bookmakers", []) or []:
        if not isinstance(b, dict) or b.get("title") != book:
            continue
        for m in b.get("markets", []) or []:
            if m.get("key") != "spreads":
                continue
            out = []
            for o in m.get("outcomes", []) or []:
                name = o.get("name")
                point = o.get("point")
                price = o.get("price")
                if name is None or price is None:
                    continue
                out.append((name, point, american_to_decimal(price)))
            return out
    return []
