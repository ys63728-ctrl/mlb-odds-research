"""
MLB Odds Research BOT のエントリーポイント。

実行方法:
    python scripts/run_bot.py

事前準備:
    1. プロジェクトルートで `pip install -r requirements.txt`
    2. `.env` に DISCORD_TOKEN / CHANNEL_ID / ODDS_API_KEY を設定
    3. BOTを通知先のDiscordサーバ＆チャンネルに参加させておく
"""

import sys
from pathlib import Path

# Windows の日本語環境では画面出力が cp932 になり、絵文字(✅など)を含む
# print がエラー(UnicodeEncodeError)で落ちる。出力を UTF-8 に切り替えて防ぐ。
for _stream in (sys.stdout, sys.stderr):
    try:
        # line_buffering=True: バックグラウンド実行でもログが1行ごとに出るようにする
        _stream.reconfigure(encoding="utf-8", line_buffering=True)
    except (AttributeError, ValueError):
        pass

# このスクリプトを scripts/ から実行しても src を import できるよう、
# プロジェクトルートを sys.path に追加する。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.database import init_db  # noqa: E402
from src.notifier.discord_bot import run  # noqa: E402


if __name__ == "__main__":
    init_db()  # DBの表がまだ無ければここで作る
    run()
