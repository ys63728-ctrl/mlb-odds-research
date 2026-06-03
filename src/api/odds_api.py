"""
The Odds API の窓口。

外部のオッズ取得APIに HTTP リクエストを投げて、生のJSONリストを返す。
通信エラー時は空リストを返し、上の階層を止めない（既存BOTの挙動を踏襲）。
"""

import requests

from src import config


ODDS_API_BASE = "https://api.the-odds-api.com/v4"


def get_current_games(
    sport_key: str | None = None,
    regions: str | None = None,
    markets: str | None = None,
) -> list[dict]:
    """
    指定スポーツの現在オッズを取得する。

    引数を省略した場合は config の値を使う。将来 NBA・サッカー等に切り替える
    ときは config.SPORT_KEY を変えるか、sport_key を指定して呼べばよい。

    返り値:
        試合一覧の list。各要素は The Odds API の生のJSON dict。
        通信失敗時は空リスト。
    """
    sport = sport_key or config.SPORT_KEY
    url = f"{ODDS_API_BASE}/sports/{sport}/odds/"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "regions": regions or config.ODDS_REGIONS,
        "markets": markets or config.ODDS_MARKETS,
        "oddsFormat": config.ODDS_FORMAT,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
    except Exception as e:
        print(f"[odds_api] 通信エラー: {e}")
        return []

    # The Odds API は HTTP ヘッダで残クレジットを教えてくれる。ログに出す。
    remaining = response.headers.get("x-requests-remaining")
    used = response.headers.get("x-requests-used")
    if remaining is not None:
        print(f"[odds_api] 使用済み: {used} / 残り: {remaining}")

    if response.status_code != 200:
        print(f"[odds_api] APIエラー: {response.status_code} {response.text[:200]}")
        return []

    try:
        data = response.json()
    except Exception as e:
        print(f"[odds_api] JSON解釈エラー: {e}")
        return []

    if not isinstance(data, list):
        print(f"[odds_api] 返答が想定外: {data}")
        return []

    return data
