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


# サッカー。The Odds API が返す英語表記をキーにする（完全一致でないと変換されない）。
# クラブ(5大リーグ+CL等)＋代表(ネーションズリーグ/W杯)。未登録は英語のまま。
SOCCER_TEAM_NAMES_JA: dict[str, str] = {
    # --- プレミアリーグ / 英 ---
    "Arsenal": "アーセナル", "Aston Villa": "アストン・ヴィラ", "Bournemouth": "ボーンマス",
    "Brentford": "ブレントフォード", "Brighton and Hove Albion": "ブライトン",
    "Chelsea": "チェルシー", "Crystal Palace": "クリスタル・パレス", "Everton": "エバートン",
    "Fulham": "フラム", "Liverpool": "リバプール", "Manchester City": "マンチェスター・シティ",
    "Manchester United": "マンチェスター・ユナイテッド", "Newcastle United": "ニューカッスル",
    "Nottingham Forest": "ノッティンガム・フォレスト", "Tottenham Hotspur": "トッテナム",
    "Leeds United": "リーズ", "Sunderland": "サンダーランド", "Hull City": "ハル・シティ",
    "Coventry City": "コベントリー", "Ipswich Town": "イプスウィッチ",
    # --- ラ・リーガ / 西 ---
    "Barcelona": "バルセロナ", "Real Madrid": "レアル・マドリード",
    "Atlético Madrid": "アトレティコ・マドリード", "Athletic Bilbao": "アスレティック・ビルバオ",
    "Real Sociedad": "レアル・ソシエダ", "Real Betis": "ベティス", "Sevilla": "セビージャ",
    "Valencia": "バレンシア", "Villarreal": "ビジャレアル", "Celta Vigo": "セルタ",
    "Getafe": "ヘタフェ", "Espanyol": "エスパニョール", "Alavés": "アラベス",
    "Rayo Vallecano": "ラージョ・バジェカーノ", "CA Osasuna": "オサスナ", "Levante": "レバンテ",
    "Elche CF": "エルチェ", "Málaga": "マラガ", "Deportivo La Coruña": "デポルティボ",
    "Real Racing Club de Santander": "ラシン・サンタンデール",
    # --- セリエA / 伊 ---
    "AC Milan": "ミラン", "Inter Milan": "インテル", "Juventus": "ユベントス",
    "Napoli": "ナポリ", "AS Roma": "ローマ", "Lazio": "ラツィオ",
    "Atalanta BC": "アタランタ", "Fiorentina": "フィオレンティーナ", "Bologna": "ボローニャ",
    "Torino": "トリノ", "Udinese": "ウディネーゼ", "Genoa": "ジェノア", "Cagliari": "カリアリ",
    "Lecce": "レッチェ", "Sassuolo": "サッスオーロ", "Parma": "パルマ", "Como": "コモ",
    "Monza": "モンツァ", "Venezia": "ベネチア", "Frosinone": "フロジノーネ",
    # --- ブンデスリーガ / 独 ---
    "Bayern Munich": "バイエルン", "Borussia Dortmund": "ドルトムント",
    "RB Leipzig": "ライプツィヒ", "Bayer Leverkusen": "レバークーゼン",
    "Eintracht Frankfurt": "フランクフルト", "VfB Stuttgart": "シュツットガルト",
    "Borussia Monchengladbach": "ボルシアMG", "Union Berlin": "ウニオン・ベルリン",
    "SC Freiburg": "フライブルク", "TSG Hoffenheim": "ホッフェンハイム",
    "FSV Mainz 05": "マインツ", "Werder Bremen": "ブレーメン", "Augsburg": "アウクスブルク",
    "1. FC Köln": "ケルン", "FC Schalke 04": "シャルケ", "Hamburger SV": "ハンブルガーSV",
    "SC Paderborn": "パーダーボルン", "Elversberg": "エルファースベルク",
    # --- リーグアン / 仏 ---
    "Paris Saint Germain": "パリSG", "Marseille": "マルセイユ", "AS Monaco": "モナコ",
    "Lyon": "リヨン", "Lille": "リール", "Nice": "ニース", "RC Lens": "ランス",
    "Rennes": "レンヌ", "Strasbourg": "ストラスブール", "Toulouse": "トゥールーズ",
    "Brest": "ブレスト", "Auxerre": "オセール", "Angers": "アンジェ", "Lorient": "ロリアン",
    "Le Havre": "ル・アーブル", "Paris FC": "パリFC", "Le Mans FC": "ル・マン", "Troyes": "トロワ",
    # --- CL/その他クラブ ---
    "Porto": "ポルト", "Sporting Lisbon": "スポルティング", "Club Brugge": "ブルージュ",
    "PSV Eindhoven": "PSVアイントホーフェン", "Feyenoord": "フェイエノールト",
    "Galatasaray": "ガラタサライ", "Fenerbahce": "フェネルバフチェ",
    "Shakhtar Donetsk": "シャフタール", "Slavia Praha": "スラビア・プラハ",
    "Bodø/Glimt": "ボドー・グリムト", "Viking FK": "バイキング", "AEK Athens": "AEKアテネ",
    "LASK": "LASK", "Sabah FK": "サバフ", "ŠK Slovan Bratislava": "スロバン",
    # --- 代表（ネーションズリーグ / W杯） ---
    "England": "イングランド", "Germany": "ドイツ", "France": "フランス", "Spain": "スペイン",
    "Italy": "イタリア", "Portugal": "ポルトガル", "Netherlands": "オランダ", "Belgium": "ベルギー",
    "Croatia": "クロアチア", "Serbia": "セルビア", "Poland": "ポーランド", "Switzerland": "スイス",
    "Austria": "オーストリア", "Denmark": "デンマーク", "Norway": "ノルウェー",
    "Sweden": "スウェーデン", "Scotland": "スコットランド", "Wales": "ウェールズ",
    "Turkey": "トルコ", "Ukraine": "ウクライナ", "Czech Republic": "チェコ",
    "Hungary": "ハンガリー", "Greece": "ギリシャ", "Romania": "ルーマニア",
    "Republic of Ireland": "アイルランド", "Iceland": "アイスランド", "Finland": "フィンランド",
    "Israel": "イスラエル", "Slovenia": "スロベニア", "Slovakia": "スロバキア",
    "Albania": "アルバニア", "Bosnia and Herzegovina": "ボスニア",
    "North Macedonia": "北マケドニア", "Montenegro": "モンテネグロ", "Georgia": "ジョージア",
    "Armenia": "アルメニア", "Azerbaijan": "アゼルバイジャン", "Malta": "マルタ",
    "Andorra": "アンドラ", "Luxembourg": "ルクセンブルク", "Kosovo": "コソボ",
    "Cyprus": "キプロス", "Estonia": "エストニア", "Latvia": "ラトビア",
    "Lithuania": "リトアニア", "Moldova": "モルドバ", "Bulgaria": "ブルガリア",
    "Kazakhstan": "カザフスタン", "Faroe Islands": "フェロー諸島", "Gibraltar": "ジブラルタル",
    "Liechtenstein": "リヒテンシュタイン", "San Marino": "サンマリノ",
}


# NBA 30球団。The Odds API が返す英語表記をキーにする。
NBA_TEAM_NAMES_JA: dict[str, str] = {
    "Atlanta Hawks": "ホークス",
    "Boston Celtics": "セルティックス",
    "Brooklyn Nets": "ネッツ",
    "Charlotte Hornets": "ホーネッツ",
    "Chicago Bulls": "ブルズ",
    "Cleveland Cavaliers": "キャバリアーズ",
    "Dallas Mavericks": "マーベリックス",
    "Denver Nuggets": "ナゲッツ",
    "Detroit Pistons": "ピストンズ",
    "Golden State Warriors": "ウォリアーズ",
    "Houston Rockets": "ロケッツ",
    "Indiana Pacers": "ペイサーズ",
    "Los Angeles Clippers": "クリッパーズ",
    "Los Angeles Lakers": "レイカーズ",
    "Memphis Grizzlies": "グリズリーズ",
    "Miami Heat": "ヒート",
    "Milwaukee Bucks": "バックス",
    "Minnesota Timberwolves": "ティンバーウルブズ",
    "New Orleans Pelicans": "ペリカンズ",
    "New York Knicks": "ニックス",
    "Oklahoma City Thunder": "サンダー",
    "Orlando Magic": "マジック",
    "Philadelphia 76ers": "シクサーズ",
    "Phoenix Suns": "サンズ",
    "Portland Trail Blazers": "トレイルブレイザーズ",
    "Sacramento Kings": "キングス",
    "San Antonio Spurs": "スパーズ",
    "Toronto Raptors": "ラプターズ",
    "Utah Jazz": "ジャズ",
    "Washington Wizards": "ウィザーズ",
}


def to_ja(team_name: str) -> str:
    """チーム名を日本語に。MLB→サッカー→NBAの順で探し、未登録なら英語のまま返す。"""
    if team_name in MLB_TEAM_NAMES_JA:
        return MLB_TEAM_NAMES_JA[team_name]
    if team_name in SOCCER_TEAM_NAMES_JA:
        return SOCCER_TEAM_NAMES_JA[team_name]
    return NBA_TEAM_NAMES_JA.get(team_name, team_name)


def format_game_name_ja(game_name: str) -> str:
    """
    'New York Yankees vs Boston Red Sox' のような英語の試合名を
    'ヤンキース vs レッドソックス' に変換する。
    """
    if " vs " not in game_name:
        return game_name
    away, home = game_name.split(" vs ", 1)
    return f"{to_ja(away)} vs {to_ja(home)}"
