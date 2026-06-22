"""
設定をまとめた場所。

ここには「あとで変えたくなる値」を集めています。
コードの本体をいじらなくても、この config.py（と .env）を直すだけで
動きを調整できるようにするのが目的です。
"""

import os
from datetime import timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

# .env ファイルを読み込む（秘密の値はここから取得する）
# プロジェクトのルート（このファイルの2つ上）にある .env を指定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# =====================================================================
# 秘密情報（.env から読み込む。コードに直書きしない）
# =====================================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID") or 0)
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/odds_research.db")


# =====================================================================
# 対象スポーツ（将来 NBA・サッカー等を足せるよう設定で切り替え可能にする）
#   The Odds API のスポーツキー:
#     - baseball_mlb        : MLB
#     - basketball_nba      : NBA
#     - soccer_fifa_world_cup : サッカーW杯
# =====================================================================
SPORT_KEY = os.getenv("SPORT_KEY", "baseball_mlb")


# =====================================================================
# 監視対象スポーツの一覧（複数スポーツを同時に監視するための設定）
#
# 各スポーツは「窓タイプ」を持つ:
#   - WINDOW_FIXED_CLOCK : MLB方式。毎日きまった時刻帯(BASE_HOUR〜END_HOUR)を
#                          一律で監視し、窓の開始時に全試合の基準を一括取得する。
#   - WINDOW_PREGAME     : NPB方式。試合ごとに窓が動く。各試合の開始
#                          lead_minutes 分前から cutoff_minutes 分前までを監視し、
#                          窓に入った瞬間(=lead_minutes分前)のオッズをその試合の基準にする。
#
# 通知の閾値(Level1/2/3・Steam)は全スポーツ共通（下で定義する値を使う）。
# =====================================================================
WINDOW_FIXED_CLOCK = "fixed_clock"
WINDOW_PREGAME = "pregame"

# NPB の監視窓（試合開始を基準とした分）
NPB_LEAD_MINUTES = 90    # 試合開始の何分前から監視を始めるか（=基準を取る時点）
NPB_CUTOFF_MINUTES = 5   # 試合開始の何分前で監視を打ち切るか

SPORTS = [
    {
        "sport_key": "baseball_mlb",
        "label": "⚾MLB",
        "emoji": "⚾",
        "window": WINDOW_FIXED_CLOCK,
    },
    {
        "sport_key": "baseball_npb",
        "label": "⚾NPB",
        "emoji": "⚾",
        "window": WINDOW_PREGAME,
        "lead_minutes": NPB_LEAD_MINUTES,
        "cutoff_minutes": NPB_CUTOFF_MINUTES,
    },
    {
        # サッカーW杯。MLBと同じ固定時刻方式（21:00基準〜23:59まで監視）。
        # 結果は ホーム / アウェイ / Draw(引き分け) の3つ。引き分けオッズも監視対象。
        "sport_key": "soccer_fifa_world_cup",
        "label": "⚽W杯",
        "emoji": "⚽",
        "window": WINDOW_FIXED_CLOCK,
    },
]


# The Odds API の呼び出し条件
ODDS_REGIONS = "us,uk,eu"      # 取得する地域
ODDS_MARKETS = "h2h"           # 市場（h2h = 勝敗。将来 spreads/totals を追加）
ODDS_FORMAT = "american"       # オッズ形式


# =====================================================================
# 時刻・タイムゾーン
#   内部処理は UTC、基準時刻の判定・表示は JST（日本時間）で統一する
# =====================================================================
JST = timezone(timedelta(hours=9))

# 監視ウィンドウ: JST 21:00 〜 23:59
BASE_HOUR = 21
BASE_MINUTE = 0
END_HOUR = 23
END_MINUTE = 59

# 試合結果を取得する時刻（JST）。MLBの試合がほぼ終わる頃
RESULT_FETCH_HOUR = 14

# 何時間先までの試合を対象にするか
TARGET_HOURS = 24


# =====================================================================
# 監視・保存の間隔（秒）
# =====================================================================
CHECK_INTERVAL_SECONDS = 60      # 変動チェック（通知判定）の間隔
SNAPSHOT_INTERVAL_SECONDS = 300  # スナップショットをDBに保存する間隔（5分）


# =====================================================================
# 監視ブック方針
#
# - 単体変動通知（Level1/2/3）の主軸は Pinnacle 1社のみ。
#   Pinnacle の 21:00 オッズ vs 現在オッズ が動いたら通知する。
#
# - Steam Move 検知は API が返す全ブック（約44社）を対象に走らせる。
#   同じ試合・同じチームで「21:00 基準から同方向に STEAM_THRESHOLD 以上
#   動いているブック」が STEAM_MIN_BOOKS 以上同時に存在する瞬間に通知。
#
# - 全ブックのオッズはスナップショットとして DB にも保存し、後の研究に使う。
#
# 補足: Circa Sports / Bookmaker は The Odds API では取得不能（2026-05-28 実測確認）。
# =====================================================================
PRIMARY_BOOKMAKER = "Pinnacle"


# =====================================================================
# 単体変動通知（Pinnacle）のレベル閾値（デシマルオッズの絶対変化量）
#
# 全スポーツ共通。動いた絶対量がどの閾値以上かで Level を決める。
# 値を増やしたい/変えたいときは、ここの定数と LEVEL_THRESHOLDS を直すだけでよい。
# =====================================================================
LEVEL1 = 0.05
LEVEL2 = 0.075
LEVEL3 = 0.10
LEVEL4 = 0.125
LEVEL5 = 0.15
LEVEL6 = 0.175
LEVEL7 = 0.20

# (レベル番号, 閾値) を小さい順に並べたもの。get_level がこれを使って判定する。
LEVEL_THRESHOLDS = [
    (1, LEVEL1),
    (2, LEVEL2),
    (3, LEVEL3),
    (4, LEVEL4),
    (5, LEVEL5),
    (6, LEVEL6),
    (7, LEVEL7),
]


# =====================================================================
# Steam Move 検知の閾値
# =====================================================================
STEAM_THRESHOLD = 0.05   # 基準からの絶対変動がこの値以上で「動いた」と判定
STEAM_MIN_BOOKS = 3      # 同方向に動いてるブックがこの数以上で Steam 通知
STEAM_SAME_DIRECTION_ONLY = True  # 同方向に動いている時だけカウントする
STEAM_MAX_ODDS = 2.1     # この倍率以下のサイドだけを Steam の対象にする（片側だけ見れば十分なため）


# =====================================================================
# ファイルパス
# =====================================================================
DATA_DIR = PROJECT_ROOT / "data"
