"""
チーム名の英語→日本語変換。

DBには英語のまま保存し、Discord通知の表示時にだけ日本語化する。
未登録のチーム名（NBA等の将来サポート時）はそのまま英語で返す。
"""


# MLB 30球団。The Odds API が返す英語表記をキーにする。
MLB_TEAM_NAMES_JA: dict[str, str] = {
    # AL East
    "Baltimore Orioles": "オリオールズ",
    "Boston Red Sox": "レッドソックス",
    "New York Yankees": "ヤンキース",
    "Tampa Bay Rays": "レイズ",
    "Toronto Blue Jays": "ブルージェイズ",
    # AL Central
    "Chicago White Sox": "ホワイトソックス",
    "Cleveland Guardians": "ガーディアンズ",
    "Detroit Tigers": "タイガース",
    "Kansas City Royals": "ロイヤルズ",
    "Minnesota Twins": "ツインズ",
    # AL West
    "Houston Astros": "アストロズ",
    "Los Angeles Angels": "エンゼルス",
    "Athletics": "アスレチックス",
    "Oakland Athletics": "アスレチックス",
    "Seattle Mariners": "マリナーズ",
    "Texas Rangers": "レンジャーズ",
    # NL East
    "Atlanta Braves": "ブレーブス",
    "Miami Marlins": "マーリンズ",
    "New York Mets": "メッツ",
    "Philadelphia Phillies": "フィリーズ",
    "Washington Nationals": "ナショナルズ",
    # NL Central
    "Chicago Cubs": "カブス",
    "Cincinnati Reds": "レッズ",
    "Milwaukee Brewers": "ブリュワーズ",
    "Pittsburgh Pirates": "パイレーツ",
    "St. Louis Cardinals": "カージナルス",
    # NL West
    "Arizona Diamondbacks": "ダイヤモンドバックス",
    "Colorado Rockies": "ロッキーズ",
    "Los Angeles Dodgers": "ドジャース",
    "San Diego Padres": "パドレス",
    "San Francisco Giants": "ジャイアンツ",
}


def to_ja(team_name: str) -> str:
    """チーム名を日本語に。未登録なら英語のまま返す。"""
    return MLB_TEAM_NAMES_JA.get(team_name, team_name)


def format_game_name_ja(game_name: str) -> str:
    """
    'New York Yankees vs Boston Red Sox' のような英語の試合名を
    'ヤンキース vs レッドソックス' に変換する。
    """
    if " vs " not in game_name:
        return game_name
    away, home = game_name.split(" vs ", 1)
    return f"{to_ja(away)} vs {to_ja(home)}"
