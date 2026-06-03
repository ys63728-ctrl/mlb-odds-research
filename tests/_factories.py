"""
The Odds API 風の偽データを組み立てるヘルパー。
本物のAPIを叩かずに、判定ロジックを再現可能にテストするためのもの。
"""


def make_outcome(name: str, american_price: int) -> dict:
    return {"name": name, "price": american_price}


def make_bookmaker(title: str, h2h_outcomes: list) -> dict:
    return {
        "title": title,
        "markets": [{"key": "h2h", "outcomes": h2h_outcomes}],
    }


def make_game(
    game_id: str,
    away: str,
    home: str,
    commence_time_iso: str,
    bookmakers: list,
) -> dict:
    return {
        "id": game_id,
        "away_team": away,
        "home_team": home,
        "commence_time": commence_time_iso,
        "bookmakers": bookmakers,
    }
