"""NPB(日本プロ野球)が The Odds API で何社にカバーされているか調べる使い捨てスクリプト。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from src import config

BASE = "https://api.the-odds-api.com/v4"

# 1) スポーツ一覧の中の baseball 系をすべて表示（NPBがあるか確認）
r = requests.get(f"{BASE}/sports/", params={"apiKey": config.ODDS_API_KEY}, timeout=15)
print("=== sports list status:", r.status_code, "===")
if r.status_code == 200:
    for s in r.json():
        if "baseball" in s["key"]:
            print(f"  {s['key']:24} active={s['active']}  {s['title']}")

# 2) NPB のオッズを取得してブック数を数える
r2 = requests.get(
    f"{BASE}/sports/baseball_npb/odds/",
    params={
        "apiKey": config.ODDS_API_KEY,
        "regions": "us,uk,eu,au",
        "markets": "h2h",
        "oddsFormat": "american",
    },
    timeout=20,
)
print("\n=== npb odds status:", r2.status_code, "===")
print("remaining credits:", r2.headers.get("x-requests-remaining"))
if r2.status_code == 200:
    games = r2.json()
    print("games returned:", len(games))
    books = set()
    for g in games:
        bk = [b["title"] for b in g.get("bookmakers", [])]
        books.update(bk)
        print(f"  {g.get('away_team')} @ {g.get('home_team')} : {len(bk)} books")
    print("\nUNIQUE BOOKMAKERS:", len(books))
    print(sorted(books))
else:
    print(r2.text[:400])
