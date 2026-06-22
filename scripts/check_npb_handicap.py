"""
NPB が The Odds API でハンデ(alternate_spreads)を返すか確認する使い捨てチェック。

NPB開催日に実行すること:
    python scripts/check_npb_handicap.py

オフ日(試合0件)だと確認できないので、その旨を表示する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from src import config

BASE = "https://api.the-odds-api.com/v4"
SK = "baseball_npb"


def main() -> None:
    ev = requests.get(f"{BASE}/sports/{SK}/events", params={"apiKey": config.ODDS_API_KEY}, timeout=15)
    events = ev.json() if ev.status_code == 200 else []
    print(f"NPB 試合数: {len(events)} (残りクレジット {ev.headers.get('x-requests-remaining')})")
    if not events:
        print("→ 今は試合なし(オフ日)。NPB開催日に再実行してください。")
        return

    ok = 0
    for e in events[:3]:  # 最大3試合だけ確認(コスト節約)
        eid = e["id"]
        r = requests.get(
            f"{BASE}/sports/{SK}/events/{eid}/odds",
            params={"apiKey": config.ODDS_API_KEY, "regions": config.ODDS_REGIONS,
                    "markets": "alternate_spreads", "oddsFormat": "decimal"},
            timeout=20,
        )
        name = f"{e.get('away_team')} @ {e.get('home_team')}"
        if r.status_code != 200:
            print(f"  {name}: alternate_spreads エラー {r.status_code} {r.text[:120]}")
            continue
        d = r.json()
        books = d.get("bookmakers", [])
        # Pinnacle の 1.9前後ラインがあるか
        near = []
        for b in books:
            if b["title"] == "Pinnacle":
                for m in b["markets"]:
                    if m["key"] == "alternate_spreads":
                        near = [(o["name"], o.get("point"), o.get("price"))
                                for o in m["outcomes"] if o.get("price") and 1.85 <= o["price"] <= 2.05]
        print(f"  {name}: ハンデ提供ブック {len(books)}社 / Pinnacle 1.9前後: {near[:2]}")
        if books:
            ok += 1

    print()
    if ok:
        print("✅ NPBはハンデ(alternate_spreads)対応。ハンデ監視がそのまま機能します。")
    else:
        print("⚠️ NPBはハンデを返しませんでした。spreads主要ライン or h2h へのフォールバックを検討。")


if __name__ == "__main__":
    main()
