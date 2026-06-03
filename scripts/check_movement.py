"""現時点のPinnacleの動きを基準と比較して可視化。"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func

from src.db.database import get_session
from src.db.models import BaseOdds, OddsSnapshot

today = date.today()

with get_session() as s:
    last_snap = s.execute(select(func.max(OddsSnapshot.snapshot_time))).scalar()
    print(f"比較する最新スナップ: {last_snap}")
    print()

    latest = s.execute(
        select(OddsSnapshot.game_name, OddsSnapshot.team, OddsSnapshot.odds_decimal)
        .where(OddsSnapshot.snapshot_time == last_snap)
        .where(OddsSnapshot.bookmaker == "Pinnacle")
    ).all()

    base = s.execute(
        select(BaseOdds.game_name, BaseOdds.team, BaseOdds.base_odds_decimal)
        .where(BaseOdds.base_date == today)
        .where(BaseOdds.bookmaker == "Pinnacle")
    ).all()
    base_map = {(g, t): float(o) for (g, t, o) in base}

    rows = []
    for g, t, o in latest:
        b = base_map.get((g, t))
        if b is None:
            continue
        move = round(float(o) - b, 3)
        rows.append((abs(move), g, t, b, float(o), move))

    rows.sort(reverse=True)

    print(f"Pinnacle 動きの大きい順 TOP10（全{len(rows)}試合×2チーム）")
    print("-" * 100)
    print(f"{'試合':<48} {'チーム':<24} {'基準':>6} {'現在':>6} {'変動':>8}  判定")
    print("-" * 100)
    for _, g, t, b, c, m in rows[:10]:
        verdict = "🟢 LEVEL1 超え" if abs(m) >= 0.05 else "範囲内（通知なし）"
        g_short = g[:46]
        t_short = t[:22]
        print(f"{g_short:<48} {t_short:<24} {b:6.2f} {c:6.2f} {m:+8.3f}  {verdict}")
