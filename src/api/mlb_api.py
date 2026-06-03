"""
MLB Stats API の窓口（公式・無料・認証不要）。

The Odds API ではオッズはわかるが「試合結果」はわからない。
そこで MLB 公式の statsapi.mlb.com から、日付指定で試合結果を取りに行く。
将来 NBA・サッカーに広げる際は、別ファイル(api/nba_api.py 等)を足す想定。
"""

from datetime import date

import requests


MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


def get_schedule(target_date: date | str) -> list[dict]:
    """
    指定した日付のMLB試合一覧を取得する。

    返り値の各 dict のキー:
        game_pk     : MLB公式の試合ID（int）
        game_date   : 試合開始時刻（ISO文字列・UTC）
        status      : 'Preview' / 'Live' / 'Final' のいずれか
        away_team   : ビジターチーム名
        home_team   : ホームチーム名
        away_score  : ビジターのスコア（試合前は None）
        home_score  : ホームのスコア（試合前は None）

    通信失敗時は空リスト。
    """
    date_str = target_date.isoformat() if isinstance(target_date, date) else target_date

    url = f"{MLB_API_BASE}/schedule"
    params = {"sportId": 1, "date": date_str}

    try:
        response = requests.get(url, params=params, timeout=15)
    except Exception as e:
        print(f"[mlb_api] 通信エラー: {e}")
        return []

    if response.status_code != 200:
        print(f"[mlb_api] APIエラー: {response.status_code}")
        return []

    try:
        data = response.json()
    except Exception as e:
        print(f"[mlb_api] JSON解釈エラー: {e}")
        return []

    games: list[dict] = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            away = g.get("teams", {}).get("away", {})
            home = g.get("teams", {}).get("home", {})
            games.append(
                {
                    "game_pk": g.get("gamePk"),
                    "game_date": g.get("gameDate"),
                    "status": g.get("status", {}).get("abstractGameState"),
                    "away_team": away.get("team", {}).get("name"),
                    "home_team": home.get("team", {}).get("name"),
                    "away_score": away.get("score"),
                    "home_score": home.get("score"),
                }
            )
    return games
