"""
The Odds API の窓口。

外部のオッズ取得APIに HTTP リクエストを投げて、生のJSONリストを返す。
通信エラー時は空リストを返し、上の階層を止めない（既存BOTの挙動を踏襲）。
"""

import requests

from src import config
from src.utils.time_utils import parse_commence_time, is_within_24h


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


def get_events(sport_key: str | None = None) -> list[dict]:
    """
    指定スポーツの試合一覧（スケジュール）を取得する。
    /events はクレジットを消費しない。各要素に id / commence_time / 両チーム名を含む。
    通信失敗時は空リスト。
    """
    sport = sport_key or config.SPORT_KEY
    url = f"{ODDS_API_BASE}/sports/{sport}/events/"
    try:
        response = requests.get(url, params={"apiKey": config.ODDS_API_KEY}, timeout=15)
    except Exception as e:
        print(f"[odds_api] events 通信エラー: {e}")
        return []
    if response.status_code != 200:
        print(f"[odds_api] events APIエラー: {response.status_code} {response.text[:200]}")
        return []
    try:
        data = response.json()
    except Exception as e:
        print(f"[odds_api] events JSON解釈エラー: {e}")
        return []
    return data if isinstance(data, list) else []


def get_scores(sport_key: str | None = None, days_from: int = 3) -> list[dict]:
    """
    指定スポーツの「試合結果（スコア）」を取得する。

    /scores は最大 days_from(最大3) 日前までの完了・進行中の試合を返す。
    各要素は The Odds API の生JSON: id / commence_time / completed(bool) /
    home_team / away_team / scores(=[{"name":.., "score":".."}] or None)。
    id は /odds と同じ試合IDなので、こちらの game_id と直接突き合わせできる。
    通信失敗時は空リスト。1呼び出し=1〜2クレジット程度。
    """
    sport = sport_key or config.SPORT_KEY
    url = f"{ODDS_API_BASE}/sports/{sport}/scores/"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "daysFrom": max(1, min(int(days_from), 3)),
        "dateFormat": "iso",
    }
    try:
        response = requests.get(url, params=params, timeout=15)
    except Exception as e:
        print(f"[odds_api] scores 通信エラー: {e}")
        return []
    if response.status_code != 200:
        print(f"[odds_api] scores APIエラー: {response.status_code} {response.text[:150]}")
        return []
    try:
        data = response.json()
    except Exception as e:
        print(f"[odds_api] scores JSON解釈エラー: {e}")
        return []
    return data if isinstance(data, list) else []


def get_games_with_handicap(
    sport_key: str | None = None,
    regions: str | None = None,
    markets: str = "alternate_spreads",
) -> list[dict]:
    """
    24時間以内に始まる各試合について、ハンデの全ライン（階段）を取得する。

    一括の /odds では主要ライン1本しか返らないため、試合ごとの専用エンドポイント
    (/events/{id}/odds) を markets=alternate_spreads で叩いて全ハンデを取る。
    各 events/{id}/odds 呼び出しは [地域数] クレジットを消費する。

    返り値:
        get_current_games と同じ形（試合 dict の list）。各 dict の bookmakers→
        markets(key='alternate_spreads')→outcomes は name/price/point を持つ。
        24時間以内に始まる試合のみが対象（監視対象と同じ範囲）。
    """
    sport = sport_key or config.SPORT_KEY
    reg = regions or config.ODDS_REGIONS

    events = get_events(sport)
    games: list[dict] = []
    last_remaining = None
    fetched = 0

    for ev in events:
        commence_str = ev.get("commence_time")
        if not commence_str:
            continue
        try:
            commence = parse_commence_time(commence_str)
        except Exception:
            continue
        if not is_within_24h(commence):
            continue  # 監視対象（24時間以内）の試合だけ階段を取りに行く

        eid = ev.get("id")
        if not eid:
            continue
        url = f"{ODDS_API_BASE}/sports/{sport}/events/{eid}/odds/"
        params = {
            "apiKey": config.ODDS_API_KEY,
            "regions": reg,
            "markets": markets,
            "oddsFormat": config.ODDS_FORMAT,
        }
        try:
            r = requests.get(url, params=params, timeout=15)
        except Exception as e:
            print(f"[odds_api] handicap 通信エラー ({eid}): {e}")
            continue

        last_remaining = r.headers.get("x-requests-remaining") or last_remaining
        if r.status_code != 200:
            print(f"[odds_api] handicap APIエラー {r.status_code}: {r.text[:150]}")
            continue
        try:
            data = r.json()
        except Exception:
            continue
        if isinstance(data, dict) and data.get("bookmakers"):
            games.append(data)
            fetched += 1

    if last_remaining is not None:
        print(f"[odds_api] handicap {fetched}試合取得 / 残り: {last_remaining}")
    return games
