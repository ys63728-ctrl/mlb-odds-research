"""
APIの動作確認スクリプト。

The Odds API と MLB Stats API の両方に実通信して、
ちゃんとデータが取れているか目視確認するためのもの。

実行: python scripts/check_apis.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# プロジェクトルートを sys.path に追加（このスクリプトから src を import できるように）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.odds_api import get_current_games
from src.api.mlb_api import get_schedule


def check_odds_api() -> None:
    print("=" * 60)
    print("The Odds API 動作確認")
    print("=" * 60)

    games = get_current_games()
    print(f"取得試合数: {len(games)}")

    if not games:
        print("  → 試合が取れませんでした。APIキー/プラン/シーズンを確認してください。")
        return

    g = games[0]
    print(f"\n[サンプル: 最初の試合]")
    print(f"  {g.get('away_team')} vs {g.get('home_team')}")
    print(f"  開始時刻: {g.get('commence_time')}")
    print(f"  game_id : {g.get('id')}")

    books_in_first = sorted({b.get("title") for b in g.get("bookmakers", [])})
    print(f"  含まれるブック数: {len(books_in_first)}")
    print(f"  含まれるブック  : {books_in_first}")

    # 全試合をまたいで「APIから出現したブック」を集計
    all_books: set[str] = set()
    for gm in games:
        for b in gm.get("bookmakers", []):
            title = b.get("title")
            if title:
                all_books.add(title)

    print(f"\n[全試合で出現したブック ({len(all_books)} 件)]")
    for b in sorted(all_books):
        print(f"  - {b}")

    # 目当てのブックが取れているかチェック
    targets = ["Pinnacle", "William Hill", "Circa Sports", "Bookmaker"]
    print(f"\n[目当てのブックが取れているか]")
    for t in targets:
        mark = "✓" if t in all_books else "✗"
        print(f"  {mark} {t}")


def check_mlb_api() -> None:
    print("\n" + "=" * 60)
    print("MLB Stats API 動作確認（昨日の試合）")
    print("=" * 60)

    yesterday = date.today() - timedelta(days=1)
    games = get_schedule(yesterday)
    print(f"{yesterday} の試合数: {len(games)}")

    if not games:
        print("  → 試合がありませんでした。オフシーズン中の可能性があります。")
        return

    print(f"\n[最大5試合まで表示]")
    for g in games[:5]:
        if g["away_score"] is not None and g["home_score"] is not None:
            score = f"{g['away_score']}-{g['home_score']}"
        else:
            score = "(未開始/進行中)"
        print(
            f"  [{g['status']:<8}] {g['away_team']} {score} {g['home_team']}"
            f"  gamePk={g['game_pk']}"
        )


if __name__ == "__main__":
    check_odds_api()
    check_mlb_api()
